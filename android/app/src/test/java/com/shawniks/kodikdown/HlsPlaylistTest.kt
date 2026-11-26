package com.shawniks.kodikdown

import com.shawniks.kodikdown.data.PlayerPage
import com.shawniks.kodikdown.data.PlayerPayload
import com.shawniks.kodikdown.downloader.DownloadLimiter
import com.shawniks.kodikdown.downloader.HlsPlaylist
import com.shawniks.kodikdown.kodik.KodikDecoder
import com.shawniks.kodikdown.util.FileUtils
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import org.junit.Test

class HlsPlaylistTest {
    @Test fun discontinuitySequenceDoesNotImplyStreamDiscontinuities() {
        val media = HlsPlaylist.parse("https://cdn.example/index.m3u8",
            "#EXTM3U\n#EXT-X-DISCONTINUITY-SEQUENCE:4\n#EXTINF:1,\nclip.ts\n#EXT-X-ENDLIST")
        assertEquals(1, media.segments.size)
    }
    private val base = "https://cdn.example/path/playlist.m3u8?token=keep"

    @Test
    fun mediaUrlsKeepTheirOwnQueries() {
        val media =
            HlsPlaylist.parse(base, "#EXTM3U\n#EXTINF:1,\nsegment.ts?token=a%2Bb\n#EXT-X-ENDLIST")
        assertEquals("https://cdn.example/path/segment.ts?token=a%2Bb", media.segments.single().url)
    }

    @Test
    fun queryOnlyReferencesKeepThePlaylistPath() {
        val media = HlsPlaylist.parse(base, "#EXTM3U\n?token=segment\n#EXT-X-ENDLIST")
        assertEquals("https://cdn.example/path/playlist.m3u8?token=segment", media.segments.single().url)
    }

    @Test
    fun utf8BomIsNotTreatedAsASegment() {
        val media = HlsPlaylist.parse(base, "\uFEFF#EXTM3U\nclip.ts\n#EXT-X-ENDLIST")
        assertEquals("https://cdn.example/path/clip.ts", media.segments.single().url)
    }

    @Test
    fun byteRangesUsePreviousEndForTheSameFile() {
        val media =
            HlsPlaylist.parse(
                base,
                "#EXTM3U\n#EXT-X-BYTERANGE:10@20\nvideo.ts\n#EXT-X-BYTERANGE:5\nvideo.ts\n#EXT-X-ENDLIST",
            )
        assertEquals(HlsPlaylist.ByteRange(20, 10), media.segments[0].range)
        assertEquals(HlsPlaylist.ByteRange(30, 5), media.segments[1].range)
    }

    @Test(expected = IOException::class)
    fun byteRangeCannotContinueInADifferentFile() {
        HlsPlaylist.parse(
            base,
            "#EXTM3U\n#EXT-X-BYTERANGE:10@0\none.ts\n#EXT-X-BYTERANGE:5\ntwo.ts\n#EXT-X-ENDLIST",
        )
    }

    @Test(expected = IOException::class)
    fun byteRangeCannotContinueAfterAnUnrangedSegment() {
        HlsPlaylist.parse(base, "#EXTM3U\nvideo.ts\n#EXT-X-BYTERANGE:5\nvideo.ts\n#EXT-X-ENDLIST")
    }

    @Test(expected = IOException::class)
    fun byteRangesCannotBeOverwrittenBeforeASegment() {
        HlsPlaylist.parse(
            base,
            "#EXTM3U\n#EXT-X-BYTERANGE:10@0\n#EXT-X-BYTERANGE:5@10\nvideo.ts\n#EXT-X-ENDLIST",
        )
    }

    @Test(expected = IOException::class)
    fun initSegmentCannotBeAppliedToEarlierSegments() {
        HlsPlaylist.parse(
            base,
            "#EXTM3U\nfirst.ts\n#EXT-X-MAP:URI=\"init.mp4\"\nsecond.m4s\n#EXT-X-ENDLIST",
        )
    }

    @Test(expected = IOException::class)
    fun keyframeOnlyPlaylistCannotBeSavedAsNormalVideo() {
        HlsPlaylist.parse(base, "#EXTM3U\n#EXT-X-I-FRAMES-ONLY\nvideo.m4s\n#EXT-X-ENDLIST")
    }

    @Test(expected = IOException::class)
    fun encryptedHlsIsRejectedBeforeDownload() {
        HlsPlaylist.parse(
            base,
            "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key\"\nsegment.ts\n#EXT-X-ENDLIST",
        )
    }

    @Test(expected = IOException::class)
    fun htmlIsNotAVideoPlaylist() {
        HlsPlaylist.parse(base, "<html>Gateway error</html>")
    }

    @Test(expected = IOException::class)
    fun livePlaylistIsRejected() {
        HlsPlaylist.parse(base, "#EXTM3U\n#EXTINF:1,\nsegment.ts")
    }

    @Test
    fun masterRespectsSelectedQuality() {
        val text =
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=1280x720\nhd.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360\nsd.m3u8"
        assertEquals("https://cdn.example/path/sd.m3u8", HlsPlaylist.selectVariant(base, text, 360))
    }

    @Test
    fun selectedResolutionTakesPriorityOverBitrate() {
        val text = """
            #EXTM3U
            #EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=640x360
            high-bitrate-sd.m3u8
            #EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=1280x720
            hd.m3u8
        """.trimIndent()
        assertEquals("https://cdn.example/path/hd.m3u8", HlsPlaylist.selectVariant(base, text, 720))
    }

    @Test(expected = IOException::class)
    fun separateAudioIsNotSilentlyLost() {
        HlsPlaylist.selectVariant(
            base,
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900,AUDIO=\"audio\"\nvideo.m3u8",
        )
    }

    @Test
    fun signedManifestKeepsQueryWhenSelectingMp4() {
        assertEquals(
            "https://cdn/480.mp4?sign=a%2Bb",
            KodikDecoder.streamKind("https://cdn/480.mp4:hls:manifest.m3u8?sign=a%2Bb").second,
        )
    }

    @Test
    fun refSignaturesPreserveLiteralPlus() {
        val payload = PlayerPayload("video", "42", "hash")
        val page =
            PlayerPage(
                payload,
                "",
                urlParams =
                    mapOf("ref" to "https%3A%2F%2Fsite.example%2Fa+b", "ref_sign" to "signature"),
            )
        assertEquals("https://site.example/a+b", page.signedForm(payload)["ref"])
    }

    @Test
    fun publicFoldersAreValidated() {
        assertEquals(
            "Download/KodikDown",
            FileUtils.publicDirectory("/storage/emulated/0/Download/KodikDown"),
        )
        assertThrows(IOException::class.java) { FileUtils.publicDirectory("Download/../private") }
    }

    @Test
    fun loweringConcurrencyWaitsForExistingWorkers() = runBlocking {
        withTimeout(5000) {
            val limiter = DownloadLimiter(2)
            val release = CompletableDeferred<Unit>()
            val entered = CompletableDeferred<Unit>()
            val first = async {
                limiter.withSlot {
                    entered.complete(Unit)
                    release.await()
                }
            }
            entered.await()
            limiter.setLimit(1)
            val second = async { limiter.withSlot { "second" } }
            delay(50)
            assertFalse(second.isCompleted)
            release.complete(Unit)
            first.await()
            assertEquals("second", second.await())
        }
    }

    @Test
    fun cancelledWaiterDoesNotConsumeASlot() = runBlocking {
        withTimeout(5000) {
            val limiter = DownloadLimiter(1)
            val release = CompletableDeferred<Unit>()
            val entered = CompletableDeferred<Unit>()
            val first = async {
                limiter.withSlot {
                    entered.complete(Unit)
                    release.await()
                }
            }
            entered.await()
            val waiting = async { limiter.withSlot { fail("cancelled waiter entered") } }
            delay(30)
            waiting.cancel()
            waiting.join()
            release.complete(Unit)
            first.await()
            assertEquals(42, limiter.withSlot { 42 })
        }
    }
}
