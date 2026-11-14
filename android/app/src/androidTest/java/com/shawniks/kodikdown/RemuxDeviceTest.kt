package com.shawniks.kodikdown

import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaPlayer
import android.test.InstrumentationTestCase
import com.shawniks.kodikdown.downloader.AdtsFrames
import com.shawniks.kodikdown.downloader.HlsDownloader
import java.io.File
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking

@Suppress("DEPRECATION")
class RemuxDeviceTest : InstrumentationTestCase() {
    fun testTransportStreamRemuxHasRawAudioAndPlayableVideo() = verifyRemux(android.os.Build.VERSION.SDK_INT < 25)

    fun testAndroid7CompatibilityMuxerPreservesBFramesAndRawAudio() = verifyRemux(true)

    private fun verifyRemux(compatibility: Boolean): Unit = runBlocking {
        val context = instrumentation.targetContext
        val input = File(context.cacheDir, "qa-remux.ts")
        val output = File(context.cacheDir, "qa-remux.mp4")
        instrumentation.context.assets.open("remux.ts").use { source ->
            input.outputStream().use { source.copyTo(it) }
        }
        try {
            HlsDownloader().remuxToMp4(input, output, compatibility = compatibility) { false }
            checkAudioAndPlayback(output)
            val extractor = MediaExtractor()
            try {
                extractor.setDataSource(output.absolutePath)
                val video = (0 until extractor.trackCount).first {
                    extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true
                }
                extractor.selectTrack(video)
                var last = -1L
                var reordered = false
                while (extractor.sampleTrackIndex >= 0) {
                    if (extractor.sampleTime < last) reordered = true
                    last = extractor.sampleTime
                    extractor.advance()
                }
                assertTrue("B-frame composition timestamps were lost", reordered)
            } finally { extractor.release() }
        } catch (error: Throwable) {
            output.takeIf { it.isFile }?.copyTo(File(context.filesDir, "qa-muxer-failure.mp4"), overwrite = true)
            throw error
        } finally {
            input.delete()
            output.delete()
        }
    }

    // Optional recovered reproduction file, copied via ADB for device playback validation.
    fun testRepairedUserFile() {
        val input = File(instrumentation.targetContext.cacheDir, "qa-user-repaired.mp4")
        if (input.exists()) checkAudioAndPlayback(input)
    }

    private fun checkAudioAndPlayback(file: File) {
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(file.absolutePath)
            val audio = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true
            } ?: error("Missing audio track; formats=" + (0 until extractor.trackCount).map { extractor.getTrackFormat(it).toString() })
            extractor.selectTrack(audio)
            val buffer = ByteBuffer.allocate(128 * 1024)
            var count = 0
            var lastTime = -1L
            while (count < 300) {
                buffer.clear()
                val size = extractor.readSampleData(buffer, 0)
                if (size < 0) break
                assertFalse("ADTS headers leaked into MP4", AdtsFrames.isAdts(buffer, size))
                assertTrue("Audio timestamps must increase", extractor.sampleTime > lastTime)
                lastTime = extractor.sampleTime
                count++
                extractor.advance()
            }
            assertTrue("Missing AAC frames", count > 100)
        } finally {
            extractor.release()
        }
        val ready = CountDownLatch(1)
        lateinit var player: MediaPlayer
        instrumentation.runOnMainSync { player = MediaPlayer() }
        try {
            instrumentation.runOnMainSync {
                player.setDataSource(file.absolutePath)
                player.setOnPreparedListener { ready.countDown() }
                player.prepareAsync()
            }
            assertTrue("Video cannot be opened", ready.await(15, TimeUnit.SECONDS))
            assertTrue(player.duration > 3000)
        } finally {
            instrumentation.runOnMainSync { player.release() }
        }
    }
}
