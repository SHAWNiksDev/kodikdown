package com.shawniks.kodikdown.kodik

import android.util.Base64
import java.nio.charset.StandardCharsets
import java.util.regex.Pattern

object KodikDecoder {
    private const val SHIFT_BOUND = 26
    const val KNOWN_SHIFT = 18

    private val URL_PREFIXES = listOf("https://", "http://", "//")
    private val HOST_PATTERN = Pattern.compile("^(?://|https?://)([^/?#\\s]+)")
    private val HLS_SUFFIX = ":hls:manifest.m3u8"
    private val DASH_SUFFIX = ":dash:manifest.mpd"

    fun caesar(text: String, shift: Int): String {
        val out = StringBuilder(text.length)
        val s = (shift % SHIFT_BOUND + SHIFT_BOUND) % SHIFT_BOUND
        for (char in text) {
            when (char) {
                in 'a'..'z' -> {
                    val base = 'a'.code
                    out.append(((char.code - base + s) % SHIFT_BOUND + base).toChar())
                }
                in 'A'..'Z' -> {
                    val base = 'A'.code
                    out.append(((char.code - base + s) % SHIFT_BOUND + base).toChar())
                }
                else -> out.append(char)
            }
        }
        return out.toString()
    }

    private fun looksLikeUrl(value: String): Boolean {
        if (URL_PREFIXES.none { value.startsWith(it) } || value.contains(" ")) {
            return false
        }
        val matcher = HOST_PATTERN.matcher(value)
        if (!matcher.find()) {
            return false
        }
        val host = matcher.group(1)?.substringBefore(':') ?: return false
        return host.contains(".") || host == "localhost"
    }

    fun decodeStreamUrl(encoded: String, knownShift: Int = KNOWN_SHIFT): Pair<String, Int>? {
        val text = encoded.filterNot { it.isWhitespace() }
        if (text.isEmpty()) return null
        if (looksLikeUrl(text)) return Pair(text, 0)
        if (text.length < 8) return null

        val shifts = mutableListOf<Int>()
        shifts.add(knownShift)
        for (shift in 0 until SHIFT_BOUND) {
            if (shift != knownShift) shifts.add(shift)
        }

        for (shift in shifts) {
            var rotated = caesar(text, shift)
            val remainder = rotated.length % 4
            if (remainder > 0) {
                rotated += "=".repeat(4 - remainder)
            }
            try {
                val decodedBytes = Base64.decode(rotated, Base64.DEFAULT)
                val decoded = String(decodedBytes, StandardCharsets.UTF_8)
                if (looksLikeUrl(decoded)) {
                    return Pair(decoded, shift)
                }
            } catch (_: Exception) {
                continue
            }
        }
        return null
    }

    fun normaliseUrl(url: String): String {
        return if (url.startsWith("http")) url else "https:$url"
    }

    fun streamKind(url: String): Pair<String, String?> {
        if (url.endsWith(HLS_SUFFIX)) {
            val direct = url.substring(0, url.length - HLS_SUFFIX.length)
            return Pair("hls", direct)
        }
        if (url.endsWith(DASH_SUFFIX)) {
            return Pair("dash", null)
        }
        val clean = url.substringBefore('?').lowercase()
        if (clean.endsWith(".m3u8")) {
            return Pair("hls", null)
        }
        if (clean.endsWith(".mpd")) {
            return Pair("dash", null)
        }
        if (clean.endsWith(".mp4")) {
            return Pair("mp4", url)
        }
        return Pair("hls", null)
    }
}
