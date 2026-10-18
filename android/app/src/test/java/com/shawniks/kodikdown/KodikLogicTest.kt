package com.shawniks.kodikdown

import com.shawniks.kodikdown.kodik.KodikDecoder
import com.shawniks.kodikdown.kodik.KodikParser
import com.shawniks.kodikdown.util.FileUtils
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class KodikLogicTest {

    @Test
    fun testCaesarCipher() {
        assertEquals("def", KodikDecoder.caesar("abc", 3))
        assertEquals("abc", KodikDecoder.caesar("def", -3))
        assertEquals("Hello, World!", KodikDecoder.caesar("Hello, World!", 26))
        assertEquals("Khoor, Zruog!", KodikDecoder.caesar("Hello, World!", 3))
    }

    @Test
    fun testSafeFileName() {
        assertEquals("video", FileUtils.safeFileName(""))
        assertEquals("clean_name", FileUtils.safeFileName("clean/name"))
        assertEquals("clip", FileUtils.safeFileName("clip.mp4"))
        assertEquals("_con", FileUtils.safeFileName("con.mp4"))
        assertEquals("My Movie", FileUtils.safeFileName("My   Movie"))
    }

    @Test
    fun testExtractEmbed() {
        val url = "https://kodikplayer.com/seria/1304528/932d5da818729ec5ccc9be7968ee3717/720p?episode=1&season=1"
        val embed = KodikParser.extractEmbed(url)
        assertEquals("kodikplayer.com", embed.domain)
        assertEquals("seria", embed.mediaType)
        assertEquals("1304528", embed.videoId)
        assertEquals("932d5da818729ec5ccc9be7968ee3717", embed.contentHash)
        assertEquals(720, embed.quality)
        assertEquals("episode=1&season=1", embed.query)
    }

    @Test
    fun testExtractEmbedFromIframe() {
        val iframe = """<iframe src="//kodik.info/video/42/0123456789abcdef0123" width="640" height="360"></iframe>"""
        val embed = KodikParser.extractEmbed(iframe)
        assertEquals("kodik.info", embed.domain)
        assertEquals("video", embed.mediaType)
        assertEquals("42", embed.videoId)
        assertEquals("0123456789abcdef0123", embed.contentHash)
        assertNull(embed.quality)
    }

    @Test
    fun testStreamKind() {
        val (hlsKind, direct) = KodikDecoder.streamKind("https://example.com/stream:hls:manifest.m3u8")
        assertEquals("hls", hlsKind)
        assertEquals("https://example.com/stream", direct)

        val (mp4Kind, mp4Direct) = KodikDecoder.streamKind("https://example.com/stream.mp4")
        assertEquals("mp4", mp4Kind)
        assertEquals("https://example.com/stream.mp4", mp4Direct)
    }
}
