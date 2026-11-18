package com.shawniks.kodikdown

import com.shawniks.kodikdown.data.HistoryItem
import com.shawniks.kodikdown.data.HistoryLinks
import org.junit.Assert.*
import org.junit.Test

class HistoryLinksTest {
    private val player = "https://kodikplayer.com/video/42/abcdef0123456789/720p?episode=2"
    private val cdn = "https://cloud2.solodcdn.com/useruploads/uuid/720.mp4:hls:manifest.m3u8"
    private fun record(url: String, source: String? = null) = HistoryItem(
        "id", "Title", "filename", url, 720, sourceInput = source)

    @Test fun iframeCopiesItsPlayerUrlInsteadOfTheTemporaryStream() {
        val input = "<iframe src=\"$player\"></iframe>"
        assertEquals(player, HistoryLinks.copySource(record(cdn, input)))
    }
    @Test fun originalSurvivesQualityAndStatusCopies() {
        val entry = record(cdn, player).copy(quality = 360, url = "https://cdn/360.mp4")
        assertEquals(player, HistoryLinks.copySource(entry))
    }
    @Test fun legacyCdnRecordsCannotInventAPlayerLink() {
        assertNull(HistoryLinks.copySource(record(cdn)))
    }
    @Test fun legacyPlayerLinksStillCopyCorrectly() {
        assertEquals(player, HistoryLinks.copySource(record(player)))
    }
}
