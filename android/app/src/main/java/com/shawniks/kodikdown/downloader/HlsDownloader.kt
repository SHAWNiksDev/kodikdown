package com.shawniks.kodikdown.downloader

import com.shawniks.kodikdown.kodik.KodikClient
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.URI
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

class HlsDownloader(
    private val client: OkHttpClient = KodikClient.defaultHttpClient()
) {
    companion object {
        private const val CONCURRENT_FRAGMENTS = 16
        private const val MAX_IN_FLIGHT_FRAGMENTS = 32
        private const val MAX_FRAGMENT_RETRIES = 4
        private const val BUFFER_SIZE = 128 * 1024
        private const val DISK_BUFFER_SIZE = 256 * 1024
    }

    fun refererFor(streamUrl: String): String {
        return try {
            val uri = URI(if (streamUrl.contains("://")) streamUrl else "https://${streamUrl.trimStart('/')}")
            val host = uri.host
            if (!host.isNullOrEmpty()) "https://$host/" else "https://kodikplayer.com/"
        } catch (_: Exception) {
            "https://kodikplayer.com/"
        }
    }

    suspend fun downloadDirectMp4(
        url: String,
        targetFile: File,
        isCancelled: () -> Boolean,
        onProgress: (downloaded: Long, total: Long?, speed: Long, eta: Long?) -> Unit
    ) = withContext(Dispatchers.IO) {
        val partFile = File("${targetFile.absolutePath}.part")
        if (partFile.exists()) partFile.delete()

        val request = Request.Builder()
            .url(url)
            .header("User-Agent", KodikClient.USER_AGENT)
            .header("Referer", refererFor(url))
            .build()

        var downloadedBytes = 0L
        var lastTime = System.currentTimeMillis()
        var bytesSinceLast = 0L
        var smoothedSpeed = 0L

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException("Direct download failed: HTTP ${response.code}")
            }
            val body = response.body ?: throw IOException("Empty response body")
            val totalBytes = body.contentLength().takeIf { it > 0 }

            BufferedInputStream(body.byteStream(), DISK_BUFFER_SIZE).use { input ->
                BufferedOutputStream(FileOutputStream(partFile), DISK_BUFFER_SIZE).use { output ->
                    val buffer = ByteArray(DISK_BUFFER_SIZE)
                    var read: Int
                    while (input.read(buffer).also { read = it } != -1) {
                        if (isCancelled()) {
                            partFile.delete()
                            throw InterruptedException("Download cancelled by user")
                        }
                        output.write(buffer, 0, read)
                        downloadedBytes += read
                        bytesSinceLast += read

                        val now = System.currentTimeMillis()
                        val diff = now - lastTime
                        if (diff >= 200) {
                            val instantSpeed = (bytesSinceLast * 1000) / diff
                            smoothedSpeed = if (smoothedSpeed == 0L) instantSpeed else (smoothedSpeed * 7 + instantSpeed * 3) / 10
                            val eta = if (totalBytes != null && smoothedSpeed > 0) {
                                (totalBytes - downloadedBytes).coerceAtLeast(0) / smoothedSpeed
                            } else null
                            onProgress(downloadedBytes, totalBytes, smoothedSpeed, eta)
                            lastTime = now
                            bytesSinceLast = 0L
                        }
                    }
                }
            }
        }

        if (targetFile.exists()) targetFile.delete()
        if (!partFile.renameTo(targetFile)) {
            partFile.copyTo(targetFile, overwrite = true)
            partFile.delete()
        }
        onProgress(downloadedBytes, downloadedBytes, 0L, 0L)
    }

    suspend fun downloadHls(
        manifestUrl: String,
        targetFile: File,
        isCancelled: () -> Boolean,
        onProgress: (downloaded: Long, total: Long?, speed: Long, eta: Long?) -> Unit
    ) = withContext(Dispatchers.IO) {
        val referer = refererFor(manifestUrl)

        // 1. Fetch manifest
        val manifestRequest = Request.Builder()
            .url(manifestUrl)
            .header("User-Agent", KodikClient.USER_AGENT)
            .header("Referer", referer)
            .build()

        var activeManifestUrl = manifestUrl
        var manifestResponse = client.newCall(manifestRequest).execute()
        if (!manifestResponse.isSuccessful && manifestUrl.contains("/720.mp4")) {
            manifestResponse.close()
            val fallbackUrl = manifestUrl.replace("/720.mp4", "/480.mp4")
            val fallbackReq = Request.Builder()
                .url(fallbackUrl)
                .header("User-Agent", KodikClient.USER_AGENT)
                .header("Referer", referer)
                .build()
            val fbRes = client.newCall(fallbackReq).execute()
            if (fbRes.isSuccessful) {
                activeManifestUrl = fallbackUrl
                manifestResponse = fbRes
            } else {
                fbRes.close()
                throw IOException("Failed to load HLS manifest: HTTP ${manifestResponse.code}")
            }
        }

        val manifestText = manifestResponse.use { response ->
            if (!response.isSuccessful) throw IOException("Failed to load HLS manifest: HTTP ${response.code}")
            response.body?.string().orEmpty()
        }

        // Check if master playlist
        val mediaPlaylistUrl = resolveMediaPlaylist(activeManifestUrl, manifestText)
        val finalManifestText = if (mediaPlaylistUrl != activeManifestUrl) {
            val req = Request.Builder()
                .url(mediaPlaylistUrl)
                .header("User-Agent", KodikClient.USER_AGENT)
                .header("Referer", referer)
                .build()
            client.newCall(req).execute().use { response ->
                if (!response.isSuccessful) throw IOException("Failed to load sub-manifest: HTTP ${response.code}")
                response.body?.string().orEmpty()
            }
        } else {
            manifestText
        }

        // 2. Parse segments and init segment
        val (initSegmentUrl, segmentUrls) = parseSegments(mediaPlaylistUrl, finalManifestText)
        if (segmentUrls.isEmpty()) {
            throw IOException("No media segments found in HLS playlist")
        }

        val partFile = File("${targetFile.absolutePath}.part")
        if (partFile.exists()) partFile.delete()

        val totalSegments = segmentUrls.size
        val downloadedBytes = AtomicLong(0L)
        val bytesSinceLastTick = AtomicLong(0L)
        val completedSegments = AtomicInteger(0)
        val failureRef = AtomicReference<Throwable?>(null)

        var lastTickTime = System.currentTimeMillis()
        var smoothedSpeed = 0L

        fun reportProgress(force: Boolean = false) {
            val now = System.currentTimeMillis()
            val diff = now - lastTickTime
            if (diff >= 200 || force) {
                val bytes = bytesSinceLastTick.getAndSet(0L)
                val instantSpeed = if (diff > 0) (bytes * 1000L) / diff else 0L
                smoothedSpeed = if (smoothedSpeed == 0L) instantSpeed else (smoothedSpeed * 7 + instantSpeed * 3) / 10
                val doneCount = completedSegments.get()
                val currentDownloaded = downloadedBytes.get()
                val avgBytesPerSeg = if (doneCount > 0) currentDownloaded.toDouble() / doneCount else 0.0
                val estimatedTotal = if (avgBytesPerSeg > 0) (avgBytesPerSeg * totalSegments).toLong() else null
                val remainingBytes = if (estimatedTotal != null) (estimatedTotal - currentDownloaded).coerceAtLeast(0) else null
                val eta = if (smoothedSpeed > 0 && remainingBytes != null) remainingBytes / smoothedSpeed else null

                onProgress(currentDownloaded, estimatedTotal, smoothedSpeed, eta)
                lastTickTime = now
            }
        }

        try {
            BufferedOutputStream(FileOutputStream(partFile), DISK_BUFFER_SIZE).use { output ->
                // Write init segment if present (fMP4)
                if (initSegmentUrl != null) {
                    if (isCancelled()) throw InterruptedException("Download cancelled by user")
                    val initBytes = downloadInitSegmentBytes(initSegmentUrl, referer)
                    output.write(initBytes)
                    downloadedBytes.addAndGet(initBytes.size.toLong())
                    bytesSinceLastTick.addAndGet(initBytes.size.toLong())
                    reportProgress()
                }

                // High-speed in-memory concurrent pipeline using CompletableDeferred array with immediate GC release
                val segmentDeferreds = Array<CompletableDeferred<ByteArray>?>(totalSegments) { CompletableDeferred() }
                val inFlightSemaphore = Semaphore(MAX_IN_FLIGHT_FRAGMENTS)
                val workerSemaphore = Semaphore(CONCURRENT_FRAGMENTS)

                coroutineScope {
                    // Producer: download up to 16 fragments concurrently into RAM
                    val downloadJob = launch(Dispatchers.IO) {
                        for ((index, segmentUrl) in segmentUrls.withIndex()) {
                            if (isCancelled() || failureRef.get() != null) break

                            inFlightSemaphore.acquire()

                            launch(Dispatchers.IO) {
                                workerSemaphore.withPermit {
                                    if (isCancelled() || failureRef.get() != null) {
                                        inFlightSemaphore.release()
                                        return@withPermit
                                    }

                                    var attempts = 0
                                    var success = false
                                    var lastEx: Exception? = null

                                    while (attempts < MAX_FRAGMENT_RETRIES && !success && !isCancelled() && failureRef.get() == null) {
                                        attempts++
                                        try {
                                            val bytes = downloadSegmentBytes(segmentUrl, referer, isCancelled) { bytesRead ->
                                                downloadedBytes.addAndGet(bytesRead.toLong())
                                                bytesSinceLastTick.addAndGet(bytesRead.toLong())
                                                reportProgress()
                                            }
                                            segmentDeferreds[index]?.complete(bytes)
                                            completedSegments.incrementAndGet()
                                            success = true
                                        } catch (e: Exception) {
                                            lastEx = e
                                            if (attempts < MAX_FRAGMENT_RETRIES && !isCancelled() && failureRef.get() == null) {
                                                delay(120L * attempts)
                                            }
                                        }
                                    }

                                    if (!success && !isCancelled()) {
                                        val ex = lastEx ?: IOException("Failed to download fragment $index after $MAX_FRAGMENT_RETRIES attempts")
                                        failureRef.compareAndSet(null, ex)
                                        segmentDeferreds[index]?.completeExceptionally(ex)
                                    }
                                }
                            }
                        }
                    }

                    // Consumer: write fragments sequentially with ZERO polling delays and immediate memory freeing
                    val writeJob = launch(Dispatchers.IO) {
                        for (i in 0 until totalSegments) {
                            if (isCancelled()) throw InterruptedException("Download cancelled by user")
                            val deferred = segmentDeferreds[i] ?: throw IOException("Fragment $i was already cleared")
                            val bytes = try {
                                deferred.await()
                            } catch (e: Exception) {
                                failureRef.set(e)
                                throw e
                            }
                            output.write(bytes)
                            segmentDeferreds[i] = null // Crucial: clear reference so GC immediately reclaims RAM
                            inFlightSemaphore.release()
                        }
                    }

                    writeJob.join()
                    downloadJob.cancel()
                }

                output.flush()
            }

            failureRef.get()?.let { throw it }

            if (isCancelled()) {
                partFile.delete()
                throw InterruptedException("Download cancelled by user")
            }

            if (targetFile.exists()) targetFile.delete()
            if (!partFile.renameTo(targetFile)) {
                partFile.copyTo(targetFile, overwrite = true)
                partFile.delete()
            }

            val finalSize = targetFile.length()
            onProgress(finalSize, finalSize, 0L, 0L)
        } finally {
            if (isCancelled() && partFile.exists()) {
                partFile.delete()
            }
        }
    }

    private fun downloadSegmentBytes(
        url: String,
        referer: String,
        isCancelled: () -> Boolean,
        onBytes: (Int) -> Unit
    ): ByteArray {
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", KodikClient.USER_AGENT)
            .header("Referer", referer)
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException("Segment HTTP ${response.code} for $url")
            }
            val body = response.body ?: throw IOException("Empty body for $url")
            val estSize = body.contentLength().takeIf { it > 0 }?.toInt() ?: (512 * 1024)
            val baos = ByteArrayOutputStream(estSize)

            BufferedInputStream(body.byteStream(), BUFFER_SIZE).use { input ->
                val buf = ByteArray(BUFFER_SIZE)
                var r: Int
                while (input.read(buf).also { r = it } != -1) {
                    if (isCancelled()) throw InterruptedException("Download cancelled by user")
                    baos.write(buf, 0, r)
                    onBytes(r)
                }
            }
            return baos.toByteArray()
        }
    }

    private fun downloadInitSegmentBytes(url: String, referer: String): ByteArray {
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", KodikClient.USER_AGENT)
            .header("Referer", referer)
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("Init segment HTTP ${response.code}")
            return response.body?.bytes() ?: throw IOException("Empty init segment")
        }
    }

    private fun resolveMediaPlaylist(manifestUrl: String, content: String): String {
        val lines = content.lines().map { it.trim() }
        var highestBandwidth = -1
        var bestUrl: String? = null

        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            if (line.startsWith("#EXT-X-STREAM-INF:")) {
                val bandwidth = extractBandwidth(line)
                var nextLine = ""
                var j = i + 1
                while (j < lines.size) {
                    if (lines[j].isNotEmpty() && !lines[j].startsWith("#")) {
                        nextLine = lines[j]
                        break
                    }
                    j++
                }
                if (nextLine.isNotEmpty() && bandwidth > highestBandwidth) {
                    highestBandwidth = bandwidth
                    bestUrl = resolveUrl(manifestUrl, nextLine)
                }
            }
            i++
        }
        return bestUrl ?: manifestUrl
    }

    private fun parseSegments(playlistUrl: String, content: String): Pair<String?, List<String>> {
        var initSegmentUrl: String? = null
        val segments = mutableListOf<String>()

        val lines = content.lines().map { it.trim() }
        for (line in lines) {
            if (line.startsWith("#EXT-X-MAP:")) {
                val uriMatch = Regex("""URI=["']([^"']+)["']""").find(line)
                if (uriMatch != null) {
                    initSegmentUrl = resolveUrl(playlistUrl, uriMatch.groupValues[1])
                }
            } else if (line.isNotEmpty() && !line.startsWith("#")) {
                segments.add(resolveUrl(playlistUrl, line))
            }
        }
        return Pair(initSegmentUrl, segments)
    }

    private fun resolveUrl(baseUrl: String, relative: String): String {
        return try {
            if (relative.startsWith("http://") || relative.startsWith("https://")) {
                relative
            } else if (relative.startsWith("//")) {
                "https:$relative"
            } else {
                val base = URI(baseUrl)
                base.resolve(relative).toString()
            }
        } catch (_: Exception) {
            relative
        }
    }

    private fun extractBandwidth(line: String): Int {
        val match = Regex("""BANDWIDTH=(\d+)""").find(line)
        return match?.groupValues?.get(1)?.toIntOrNull() ?: 0
    }
}
