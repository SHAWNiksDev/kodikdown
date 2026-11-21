package com.shawniks.kodikdown.downloader

import java.io.IOException
import java.net.URI

/** Parse the supported HLS subset explicitly; never save unsupported data as a successful video. */
object HlsPlaylist {
    data class ByteRange(val offset: Long, val length: Long)

    data class Segment(val url: String, val range: ByteRange? = null)

    data class Media(val init: Segment?, val segments: List<Segment>)

    private fun resolve(base: String, path: String): String = URI(base).resolve(path).toString()

    fun selectVariant(base: String, text: String, quality: Int? = null): String? {
        val lines = playlistLines(text).toList()
        val variants = mutableListOf<Triple<Int, Long, String>>()
        var hasSeparateAudio = false
        for ((index, line) in lines.withIndex()) {
            if (!line.startsWith("#EXT-X-STREAM-INF:")) continue
            val next = lines.getOrNull(index + 1)
            if (next == null || next.startsWith("#")) throw IOException("Invalid HLS variant URL")
            if (Regex("(?:[:,])AUDIO=").containsMatchIn(line)) {
                hasSeparateAudio = true
                continue
            }
            val height =
                Regex("(?:[:,])RESOLUTION=\\d+x(\\d+)")
                    .find(line)
                    ?.groupValues
                    ?.get(1)
                    ?.toIntOrNull() ?: 0
            val bandwidth =
                Regex("(?:[:,])BANDWIDTH=(\\d+)").find(line)?.groupValues?.get(1)?.toLongOrNull()
                    ?: 0
            variants.add(Triple(height, bandwidth, resolve(base, next)))
        }
        if (variants.isEmpty() && hasSeparateAudio) {
            throw IOException("HLS with a separate audio track is not supported on Android")
        }
        val eligible = if (quality == null) variants else variants.filter { it.first <= quality }
        return (eligible.maxByOrNull { it.second } ?: variants.minByOrNull { it.first })?.third
    }

    fun parse(base: String, text: String): Media {
        var init: Segment? = null
        val segments = mutableListOf<Segment>()
        var pendingRange: String? = null
        var ended = false
        for (line in playlistLines(text)) {
            when {
                line.startsWith("#EXT-X-KEY:") &&
                    !Regex("(?:[:,])METHOD=NONE(?:,|$)").containsMatchIn(line) ->
                    throw IOException("Encrypted HLS is not supported on Android")
                line == "#EXT-X-DISCONTINUITY" ->
                    throw IOException("HLS discontinuities are not supported on Android")
                line.startsWith("#EXT-X-STREAM-INF:") ->
                    throw IOException("Expected an HLS media playlist")
                line.startsWith("#EXT-X-MAP:") -> {
                    val uri =
                        Regex("URI=\"([^\"]+)\"").find(line)?.groupValues?.get(1)
                            ?: throw IOException("Missing HLS init segment URL")
                    val range = Regex("BYTERANGE=\"([^\"]+)\"").find(line)?.groupValues?.get(1)
                    val parsed = Segment(resolve(base, uri), range?.let { parseRange(it, 0) })
                    if (init != null && init != parsed)
                        throw IOException("Changing HLS init segments are not supported")
                    init = parsed
                }
                line.startsWith("#EXT-X-BYTERANGE:") -> pendingRange = line.substringAfter(':')
                line == "#EXT-X-ENDLIST" -> ended = true
                line.isNotEmpty() && !line.startsWith("#") -> {
                    val url = resolve(base, line)
                    val range = pendingRange?.let {
                        val previous = segments.lastOrNull()?.takeIf { segment -> segment.url == url }?.range
                        val offset = previous?.let { it.offset + it.length }
                        parseRange(it, offset)
                    }
                    segments.add(Segment(url, range))
                    pendingRange = null
                }
            }
        }
        if (!ended) {
            throw IOException("Live HLS playlists are not supported; use a completed video")
        }
        if (segments.isEmpty() || pendingRange != null)
            throw IOException("Incomplete HLS media playlist")
        return Media(init, segments)
    }

    private fun playlistLines(text: String): Sequence<String> {
        val lines = text.trimStart('\uFEFF', ' ', '\n', '\r', '\t')
        if (lines.lineSequence().first().trimEnd() != "#EXTM3U") {
            throw IOException("The server did not return an HLS playlist")
        }
        return lines.lineSequence().drop(1).map(String::trim).filter(String::isNotEmpty)
    }

    private fun parseRange(raw: String, offset: Long?): ByteRange {
        val parts = raw.split('@', limit = 2)
        val length = parts[0].toLongOrNull() ?: throw IOException("Invalid HLS byte range")
        val start =
            if (parts.size == 2)
                parts[1].toLongOrNull() ?: throw IOException("Invalid HLS byte offset")
            else offset ?: throw IOException("HLS byte range has no starting offset")
        if (length <= 0 || start < 0 || start > Long.MAX_VALUE - length)
            throw IOException("Invalid HLS byte range")
        return ByteRange(start, length)
    }
}
