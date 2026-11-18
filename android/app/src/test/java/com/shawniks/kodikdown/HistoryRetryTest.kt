package com.shawniks.kodikdown

import com.shawniks.kodikdown.data.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class HistoryRetryTest {
    private val source = "<iframe src=\"https://kodikplayer.com/video/42/hash\"></iframe>"
    private val original = HistoryItem("id", "title", "file", "https://expired.cdn/old", 720,
        translation = "Voice B", sourceInput = source)
    private val voiceA = Translation("Voice A", "video", "42", "a")
    private val voiceB = Translation("Voice B", "video", "43", "b")

    @Test fun refreshesSignedUrlsAndRetainsVoiceAndQuality(): Unit = runBlocking {
        val requests = mutableListOf<Translation?>()
        val retry = HistoryRetry.resolve(original) { input, voice ->
            assertEquals("https://kodikplayer.com/video/42/hash", input)
            requests.add(voice)
            ResolvedVideo("title", listOf(StreamVariant(1080, "https://fresh/1080"),
                StreamVariant(720, "https://fresh/720?signature=NEW")),
                translations = listOf(voiceA, voiceB), translation = voice ?: voiceA)
        }
        assertEquals(listOf(null, voiceB), requests)
        assertEquals("https://fresh/720?signature=NEW", retry.variant.url)
        assertEquals(720, retry.variant.quality)
        assertEquals("Voice B", retry.translation)
        assertEquals("https://kodikplayer.com/video/42/hash", retry.source)
    }

    @Test fun missingQualityUsesSuppliedLowerVariant(): Unit = runBlocking {
        val retry = HistoryRetry.resolve(original.copy(translation = null)) { _, _ ->
            ResolvedVideo("title", listOf(StreamVariant(1080, "high"), StreamVariant(480, "lower")))
        }
        assertEquals("lower", retry.variant.url)
    }

    @Test(expected = java.io.IOException::class)
    fun missingOriginalVoiceDoesNotSilentlyDownloadAnother(): Unit = runBlocking {
        HistoryRetry.resolve(original) { _, _ ->
            ResolvedVideo("title", listOf(StreamVariant(720, "fresh")), translation = voiceA)
        }
        Unit
    }

    @Test fun legacyHistoryRetainsOnlyRecoverableStream(): Unit = runBlocking {
        val retry = HistoryRetry.resolve(original.copy(sourceInput = null, isMp4 = true)) { _, _ ->
            error("Cannot derive an original player link from a CDN URL")
        }
        assertEquals(original.url, retry.variant.directMp4)
        assertNull(retry.source)
    }
}
