package com.shawniks.kodikdown.downloader

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import com.shawniks.kodikdown.kodik.KodikClient
import com.shawniks.kodikdown.net.readResponse
import java.io.File
import java.io.IOException
import java.net.URI
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import okhttp3.OkHttpClient
import okhttp3.Request

class HlsDownloader(private val client: OkHttpClient = KodikClient.defaultHttpClient().newBuilder()
    .connectTimeout(8, java.util.concurrent.TimeUnit.SECONDS)
    .readTimeout(8, java.util.concurrent.TimeUnit.SECONDS).build()) {
    companion object {
        private const val CONCURRENT_FRAGMENTS = 8
        private const val BUFFER_SIZE = 128 * 1024
        // Shared by every transfer: memory/socket use does not multiply by queue size.
        private val fragmentSlots = Semaphore(CONCURRENT_FRAGMENTS)
    }

    fun refererFor(streamUrl: String): String =
        try {
            val host = URI(if (streamUrl.startsWith("//")) "https:$streamUrl" else streamUrl).host
            if (host.isNullOrEmpty()) "https://kodikplayer.com/" else "https://$host/"
        } catch (_: Exception) {
            "https://kodikplayer.com/"
        }

    private fun request(url: String): Request.Builder =
        Request.Builder()
            .url(url)
            .header("User-Agent", KodikClient.USER_AGENT)
            .header("Referer", refererFor(url))

    suspend fun downloadDirectMp4(
        url: String,
        targetFile: File,
        isCancelled: () -> Boolean,
        onProgress: (Long, Long?, Long, Long?) -> Unit,
        onNetworkWait: (Boolean) -> Unit = {},
        onProcessing: () -> Unit = {},
    ) =
        withContext(Dispatchers.IO) {
            val part = File("${targetFile.absolutePath}.part")
            val progress = Progress(onProgress)
            try {
                var validator: String? = null
                retryNetwork(onNetworkWait) {
                    val offset = part.takeIf { it.exists() }?.length() ?: 0L
                    val builder = request(url)
                    if (offset > 0) {
                        builder.header("Range", "bytes=$offset-")
                        validator?.let { builder.header("If-Range", it) }
                    }
                    client.readResponse(builder.build()) { response ->
                        if (response.code == 416 && offset > 0 &&
                            response.header("Content-Range") == "bytes */$offset") return@readResponse
                        if (!response.isSuccessful) throw IOException("Direct download HTTP ${response.code}")
                        val append = response.code == 206 && offset > 0
                        if (append && response.header("Content-Range")?.startsWith("bytes $offset-") != true)
                            throw IOException("Invalid resume byte range")
                        validator = response.header("ETag") ?: response.header("Last-Modified")
                        val body = response.body ?: throw IOException("Empty response body")
                        var written = if (append) offset else 0L
                        val total = if (response.code == 206)
                            response.header("Content-Range")?.substringAfter('/')?.toLongOrNull()
                                ?: throw IOException("Invalid resume resource length")
                            else body.contentLength().takeIf { it >= 0 }
                        body.byteStream().buffered(BUFFER_SIZE).use { input ->
                            java.io.FileOutputStream(part, append).buffered(BUFFER_SIZE).use { output ->
                                val buffer = ByteArray(BUFFER_SIZE)
                                while (true) {
                                    checkCancelled(isCancelled)
                                    val count = input.read(buffer)
                                    if (count == -1) break
                                    output.write(buffer, 0, count)
                                    written += count
                                    onNetworkWait(false)
                                    progress.report(written, total)
                                }
                            }
                        }
                        if (written == 0L || (total != null && written != total))
                            throw IOException("Incomplete MP4 response")
                    }
                }
                currentCoroutineContext().ensureActive()
                checkCancelled(isCancelled)
                // Reject HTML/error bodies and malformed video before exposing a completed file.
                onProcessing()
                validateVideo(part)
                publish(part, targetFile)
                onProgress(targetFile.length(), targetFile.length(), 0, 0)
            } finally {
                part.delete()
            }
        }

    suspend fun downloadHls(
        manifestUrl: String,
        targetFile: File,
        isCancelled: () -> Boolean,
        quality: Int? = null,
        onFragmentProgress: (Int, Int) -> Unit = { _, _ -> },
        onProgress: (Long, Long?, Long, Long?) -> Unit,
        onNetworkWait: (Boolean) -> Unit = {},
        onProcessing: () -> Unit = {},
    ) =
        withContext(Dispatchers.IO) {
            val part = File("${targetFile.absolutePath}.part")
            val muxed = File("${targetFile.absolutePath}.mux.part")
            val fragments = File("${targetFile.absolutePath}.fragments")
            try {
                if (!fragments.mkdirs()) throw IOException("Could not create fragment cache")
                val master = loadText(manifestUrl, onNetworkWait)
                val mediaUrl =
                    HlsPlaylist.selectVariant(manifestUrl, master, quality) ?: manifestUrl
                val text = if (mediaUrl == manifestUrl) master else loadText(mediaUrl, onNetworkWait)
                val playlist = HlsPlaylist.parse(mediaUrl, text)
                val bytesWritten = AtomicLong(0)
                val progress = Progress(onProgress)
                var completedFragments = 0
                onFragmentProgress(0, playlist.segments.size)
                part.outputStream().buffered(BUFFER_SIZE).use { output ->
                    playlist.init?.let {
                        val init = loadSegment(it, File(fragments, "init"), isCancelled, onNetworkWait)
                        init.inputStream().use { input -> input.copyTo(output, BUFFER_SIZE) }
                        init.delete()
                    }
                    // Stream fragments to disk, then concatenate in playlist order.
                    // Structured cancellation joins sibling calls before cache cleanup.
                    for ((batchIndex, batch) in playlist.segments.chunked(CONCURRENT_FRAGMENTS).withIndex()) {
                        currentCoroutineContext().ensureActive()
                        checkCancelled(isCancelled)
                        coroutineScope {
                            val downloads =
                                batch.mapIndexed { index, segment -> async {
                                    loadSegment(segment, File(fragments, "$batchIndex-$index"), isCancelled, onNetworkWait)
                                } }
                            for (download in downloads) {
                                val fragment = download.await()
                                val size = fragment.length()
                                fragment.inputStream().use { input -> input.copyTo(output, BUFFER_SIZE) }
                                fragment.delete()
                                onFragmentProgress(++completedFragments, playlist.segments.size)
                                progress.report(bytesWritten.addAndGet(size), null)
                            }
                        }
                    }
                }
                currentCoroutineContext().ensureActive()
                checkCancelled(isCancelled)
                onProcessing()
                remuxToMp4(part, muxed, isCancelled = isCancelled)
                currentCoroutineContext().ensureActive()
                checkCancelled(isCancelled)
                publish(muxed, targetFile)
                onProgress(targetFile.length(), targetFile.length(), 0, 0)
            } finally {
                part.delete()
                muxed.delete()
                fragments.deleteRecursively()
            }
        }

    private suspend fun loadText(url: String, onNetworkWait: (Boolean) -> Unit): String =
        retryNetwork(onNetworkWait) { client.readResponse(request(url).build()) { response ->
            if (!response.isSuccessful) throw IOException("HLS manifest HTTP ${response.code}")
            response.body?.string() ?: throw IOException("Empty HLS manifest")
        } }

    private suspend fun loadSegment(
        segment: HlsPlaylist.Segment,
        file: File,
        isCancelled: () -> Boolean,
        onNetworkWait: (Boolean) -> Unit,
    ): File = fragmentSlots.withPermit {
        retryNetwork(onNetworkWait) {
            currentCoroutineContext().ensureActive()
            checkCancelled(isCancelled)
            val builder = request(segment.url)
            segment.range?.let {
                builder.header("Range", "bytes=${it.offset}-${it.offset + it.length - 1}")
            }
            client.readResponse(builder.build()) { response ->
                if (!response.isSuccessful) throw IOException("Segment HTTP ${response.code}")
                if (segment.range != null && response.code != 206)
                    throw IOException("Server ignored the HLS byte range")
                segment.range?.let { range ->
                    if (response.header("Content-Range")?.startsWith("bytes ${range.offset}-${range.offset + range.length - 1}/") != true)
                        throw IOException("Invalid HLS byte range response")
                }
                val body = response.body ?: throw IOException("Empty HLS segment")
                val expected = segment.range?.length ?: body.contentLength().takeIf { it >= 0 }
                var written = 0L
                body.byteStream().use { input ->
                    file.outputStream().buffered(BUFFER_SIZE).use { output ->
                        val buffer = ByteArray(BUFFER_SIZE)
                        while (true) {
                            checkCancelled(isCancelled)
                            val count = input.read(buffer)
                            if (count == -1) break
                            output.write(buffer, 0, count)
                            written += count
                        }
                    }
                }
                if (written == 0L || (expected != null && written != expected))
                    throw IOException("Incomplete HLS fragment")
                file
            }
        }
    }

    private suspend fun <T> retryNetwork(onNetworkWait: (Boolean) -> Unit,
        block: suspend () -> T): T {
        for (attempt in 0 until 6) {
            currentCoroutineContext().ensureActive()
            try {
                val result = block()
                onNetworkWait(false)
                return result
            } catch (e: IOException) {
                // Missing/denied streams belong to quality fallback, not reconnect retries.
                if (attempt == 5 || Regex("HTTP (?:400|401|403|404|410)\\b").containsMatchIn(e.message.orEmpty())) throw e
                onNetworkWait(true)
                delay(minOf(1000L * (attempt + 1), 4000L))
            }
        }
        throw IOException("Network retries exhausted")
    }

    private fun validateVideo(file: File) {
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(file.absolutePath)
            if (
                (0 until extractor.trackCount).none {
                    extractor
                        .getTrackFormat(it)
                        .getString(MediaFormat.KEY_MIME)
                        ?.startsWith("video/") == true
                }
            )
                throw IOException("The response does not contain a supported video track")
        } finally {
            extractor.release()
        }
    }

    internal suspend fun remuxToMp4(input: File, output: File,
        compatibility: Boolean = android.os.Build.VERSION.SDK_INT < 25, isCancelled: () -> Boolean) {
        val extractor = MediaExtractor()
        var muxer: Mp4Writer? = null
        try {
            extractor.setDataSource(input.absolutePath)
            val writer =
                Mp4Writer(output, compatibility)
            muxer = writer
            val tracks = mutableMapOf<Int, Int>()
            val audioTracks = mutableSetOf<Int>()
            val audioStart = mutableMapOf<Int, Long>()
            val audioFrames = mutableMapOf<Int, Long>()
            var hasVideo = false
            var bufferSize = 2 * 1024 * 1024
            for (index in 0 until extractor.trackCount) {
                val format = extractor.getTrackFormat(index)
                val mime = format.getString(MediaFormat.KEY_MIME).orEmpty()
                if (!mime.startsWith("video/") && !mime.startsWith("audio/")) continue
                hasVideo = hasVideo || mime.startsWith("video/")
                if (mime == "audio/mp4a-latm") {
                    audioTracks.add(index)
                    format.setInteger(MediaFormat.KEY_IS_ADTS, 0)
                }
                tracks[index] = writer.addTrack(format)
                extractor.selectTrack(index)
                if (format.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) {
                    bufferSize =
                        maxOf(bufferSize, format.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE))
                }
            }
            if (!hasVideo) throw IOException("HLS contains no supported video track")
            writer.start()
            val buffer = ByteBuffer.allocate(bufferSize)
            val info = MediaCodec.BufferInfo()
            var samples = 0
            while (true) {
                currentCoroutineContext().ensureActive()
                checkCancelled(isCancelled)
                buffer.clear()
                val size = extractor.readSampleData(buffer, 0)
                if (size < 0) break
                val flags =
                    if ((extractor.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0)
                        MediaCodec.BUFFER_FLAG_KEY_FRAME
                    else 0
                info.set(0, size, extractor.sampleTime, flags)
                val trackIndex = tracks[extractor.sampleTrackIndex]
                if (trackIndex == null) {
                    extractor.advance()
                    continue
                }
                if (extractor.sampleTrackIndex in audioTracks && AdtsFrames.isAdts(buffer, size)) {
                    val inputTrack = extractor.sampleTrackIndex
                    val start = audioStart.getOrPut(inputTrack) { extractor.sampleTime }
                    var frameCount = audioFrames[inputTrack] ?: 0L
                    for (frame in AdtsFrames.split(buffer, size)) {
                        info.set(frame.offset, frame.size,
                            start + frameCount * 1024L * 1_000_000L / frame.sampleRate,
                            MediaCodec.BUFFER_FLAG_KEY_FRAME)
                        buffer.position(frame.offset)
                        buffer.limit(frame.offset + frame.size)
                        writer.writeSampleData(trackIndex, buffer, info)
                        buffer.limit(buffer.capacity())
                        frameCount++
                    }
                    audioFrames[inputTrack] = frameCount
                } else {
                    writer.writeSampleData(trackIndex, buffer, info)
                }
                samples++
                extractor.advance()
            }
            if (samples == 0) throw IOException("HLS contains no video samples")
            writer.stop()
        } finally {
            extractor.release()
            muxer?.release()
        }
    }

    private fun publish(part: File, target: File) {
        if (target.exists()) throw IOException("Target already exists: ${target.name}")
        if (!part.renameTo(target)) throw IOException("Could not finalize downloaded video")
    }

    private fun checkCancelled(isCancelled: () -> Boolean) {
        if (isCancelled()) throw CancellationException("Download cancelled")
    }

    private class Progress(private val listener: (Long, Long?, Long, Long?) -> Unit) {
        private var lastTime = System.nanoTime()
        private var lastBytes = 0L

        fun report(bytes: Long, total: Long?) {
            val now = System.nanoTime()
            val elapsed = now - lastTime
            if (elapsed < 200_000_000L) return
            val speed = ((bytes - lastBytes) * 1_000_000_000L / elapsed).coerceAtLeast(0)
            listener(
                bytes,
                total,
                speed,
                if (total != null && speed > 0) (total - bytes).coerceAtLeast(0) / speed else null,
            )
            lastTime = now
            lastBytes = bytes
        }
    }
}
