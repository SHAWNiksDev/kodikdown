package com.shawniks.kodikdown.downloader

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Build
import android.util.AtomicFile
import com.shawniks.kodikdown.kodik.KodikClient
import com.shawniks.kodikdown.net.readResponse
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.net.URI
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject

internal class DownloadHttpException(val code: Int, resource: String) : IOException("$resource HTTP $code")

class HlsDownloader(private val client: OkHttpClient = KodikClient.defaultHttpClient().newBuilder()
    .connectTimeout(8, TimeUnit.SECONDS)
    .readTimeout(8, TimeUnit.SECONDS).build()) {
    companion object {
        private const val CONCURRENT_FRAGMENTS = 8
        private const val BUFFER_SIZE = 128 * 1024
        private val fullTail = Regex("bytes (\\d+)-(\\d+)/(\\d+)")
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

    private fun request(url: String, referer: String? = null): Request.Builder =
        Request.Builder()
            .url(url)
            .header("User-Agent", KodikClient.USER_AGENT)
            .header("Referer", referer ?: refererFor(url))

    suspend fun downloadDirectMp4(
        url: String,
        targetFile: File,
        isCancelled: () -> Boolean,
        onProgress: (Long, Long?, Long, Long?) -> Unit,
        onNetworkWait: (Boolean) -> Unit = {},
        onProcessing: () -> Unit = {},
        referer: String? = null,
        keepPartial: Boolean = false,
    ) =
        withContext(Dispatchers.IO) {
            val part = File("${targetFile.absolutePath}.part")
            val checkpoint = AtomicFile(File("${targetFile.absolutePath}.direct.json"))
            val identity = fingerprint(url)
            val progress = Progress(onProgress)
            try {
                var validator = if (keepPartial) readCheckpoint(checkpoint, identity)?.optString("validator")
                    ?.takeIf(String::isNotEmpty) else null
                retryNetwork(onNetworkWait) {
                    val offset = if (validator != null) part.length() else 0L
                    val builder = request(url, referer).header("Accept-Encoding", "identity")
                    if (offset > 0) {
                        builder.header("Range", "bytes=$offset-")
                        builder.header("If-Range", checkNotNull(validator))
                    }
                    client.readResponse(builder.build()) { response ->
                        if (response.code == 416 && offset > 0) {
                            validator = null
                            throw IOException("MP4 resource no longer matches the partial download")
                        }
                        if (!response.isSuccessful) throw DownloadHttpException(response.code, "Direct download")
                        val append = response.code == 206 && offset > 0
                        val etag = response.header("ETag")
                        val receivedValidator = etag?.takeUnless { it.startsWith("W/") }
                            ?: response.header("Last-Modified")
                        val body = response.body ?: throw IOException("Empty response body")
                        var written = if (append) offset else 0L
                        val total = if (response.code == 206) {
                            val range = fullTail.matchEntire(response.header("Content-Range").orEmpty())
                            val start = range?.groupValues?.get(1)?.toLongOrNull()
                            val end = range?.groupValues?.get(2)?.toLongOrNull()
                            val length = range?.groupValues?.get(3)?.toLongOrNull()
                            if (start != offset || end == null || length == null || end < offset ||
                                end != length - 1 || (append && receivedValidator != null && receivedValidator != validator)) {
                                validator = null
                                throw IOException("Invalid resume byte range")
                            }
                            length
                        } else body.contentLength().takeIf { it >= 0 }
                        validator = receivedValidator ?: if (append) validator else null
                        body.byteStream().buffered(BUFFER_SIZE).use { input ->
                            FileOutputStream(part, append).buffered(BUFFER_SIZE).use { output ->
                                if (keepPartial) {
                                    if (validator == null) checkpoint.delete()
                                    else writeCheckpoint(checkpoint, JSONObject().put("source", identity)
                                        .put("validator", validator))
                                }
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
                if (!keepPartial || targetFile.isFile) {
                    part.delete()
                    checkpoint.delete()
                }
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
        referer: String? = null,
        keepPartial: Boolean = false,
    ) =
        withContext(Dispatchers.IO) {
            val part = File("${targetFile.absolutePath}.hls.part")
            val muxed = File("${targetFile.absolutePath}.mux.part")
            val fragments = File("${targetFile.absolutePath}.fragments")
            val checkpoint = AtomicFile(File("${targetFile.absolutePath}.hls.json"))
            try {
                if (!fragments.mkdirs() && !fragments.isDirectory) throw IOException("Could not create fragment cache")
                val master = loadText(manifestUrl, onNetworkWait, referer)
                val variant = HlsPlaylist.selectVariant(master.url, master.text, quality?.takeIf { it > 0 })
                val media = if (variant == null) master else loadText(variant, onNetworkWait, referer)
                val playlist = HlsPlaylist.parse(media.url, media.text)
                val identity = fingerprint(media.url + "\n" + media.text)
                val saved = if (keepPartial) readCheckpoint(checkpoint, identity) else null
                val count = playlist.segments.size
                var done = saved?.optInt("segments", 0)?.takeIf { it in 1..count } ?: 0
                var bytesWritten = saved?.optLong("bytes", 0)?.takeIf { it in 1..part.length() } ?: 0
                if (bytesWritten == 0L) done = 0
                if (done == 0) {
                    bytesWritten = 0
                    checkpoint.delete()
                }
                RandomAccessFile(part, "rw").use { it.setLength(bytesWritten) }
                val progress = Progress(onProgress)
                onFragmentProgress(done, count)
                FileOutputStream(part, true).buffered(BUFFER_SIZE).use { output ->
                    playlist.init?.takeIf { done == 0 }?.let {
                        val init = loadSegment(it, File(fragments, "init"), isCancelled, onNetworkWait, referer)
                        init.inputStream().use { input -> input.copyTo(output, BUFFER_SIZE) }
                        bytesWritten += init.length()
                        init.delete()
                    }
                    coroutineScope {
                        val downloads = ArrayDeque<Deferred<File>>()
                        fun launchFragment(index: Int) {
                            downloads.addLast(async {
                                loadSegment(playlist.segments[index], File(fragments, "$index"),
                                    isCancelled, onNetworkWait, referer)
                            })
                        }
                        val window = minOf(CONCURRENT_FRAGMENTS, count - done)
                        repeat(window) { launchFragment(done + it) }
                        for (index in done until count) {
                            checkCancelled(isCancelled)
                            val fragment = downloads.removeFirst().await()
                            bytesWritten += fragment.length()
                            fragment.inputStream().use { input -> input.copyTo(output, BUFFER_SIZE) }
                            if (keepPartial) {
                                output.flush()
                                writeCheckpoint(checkpoint, JSONObject().put("source", identity)
                                    .put("segments", index + 1).put("bytes", bytesWritten))
                            }
                            fragment.delete()
                            if (index + window < count) launchFragment(index + window)
                            onFragmentProgress(index + 1, count)
                            progress.report(bytesWritten, null)
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
                if (!keepPartial || targetFile.isFile) {
                    part.delete()
                    checkpoint.delete()
                }
                muxed.delete()
                fragments.deleteRecursively()
            }
        }

    private fun fingerprint(value: String): String =
        MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") {
            "%02x".format(it.toInt() and 0xff)
        }

    private fun readCheckpoint(file: AtomicFile, source: String): JSONObject? =
        runCatching { JSONObject(file.readFully().toString(Charsets.UTF_8)) }.getOrNull()
            ?.takeIf { it.optString("source") == source }

    private fun writeCheckpoint(file: AtomicFile, data: JSONObject) {
        val output = file.startWrite()
        try {
            output.write(data.toString().toByteArray())
            file.finishWrite(output)
        } catch (error: IOException) {
            file.failWrite(output)
            throw error
        }
    }

    private data class Manifest(val url: String, val text: String)

    private suspend fun loadText(url: String, onNetworkWait: (Boolean) -> Unit, referer: String?): Manifest =
        retryNetwork(onNetworkWait) { client.readResponse(request(url, referer).build()) { response ->
            if (!response.isSuccessful) throw DownloadHttpException(response.code, "HLS manifest")
            Manifest(response.request.url.toString(), response.body?.string() ?: throw IOException("Empty HLS manifest"))
        } }

    private suspend fun loadSegment(
        segment: HlsPlaylist.Segment,
        file: File,
        isCancelled: () -> Boolean,
        onNetworkWait: (Boolean) -> Unit,
        referer: String?,
    ): File = fragmentSlots.withPermit {
        retryNetwork(onNetworkWait) {
            currentCoroutineContext().ensureActive()
            checkCancelled(isCancelled)
            val builder = request(segment.url, referer)
            segment.range?.let {
                builder.header("Range", "bytes=${it.offset}-${it.offset + it.length - 1}")
            }
            client.readResponse(builder.build()) { response ->
                if (!response.isSuccessful) throw DownloadHttpException(response.code, "Segment")
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
                if (attempt == 5 || (e as? DownloadHttpException)?.code in setOf(400, 401, 403, 404, 410)) throw e
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
        compatibility: Boolean = Build.VERSION.SDK_INT < 25, isCancelled: () -> Boolean) {
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
            if (elapsed <= 0L || (lastBytes > 0L && elapsed < 200_000_000L)) return
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
