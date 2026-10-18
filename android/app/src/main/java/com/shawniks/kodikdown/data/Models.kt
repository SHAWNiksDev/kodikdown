package com.shawniks.kodikdown.data

import java.net.URLDecoder
import java.nio.charset.StandardCharsets

data class EmbedInfo(
    val domain: String,
    val mediaType: String,
    val videoId: String,
    val contentHash: String,
    val quality: Int? = null,
    val query: String = ""
) {
    val path: String
        get() {
            val base = "/$mediaType/$videoId/$contentHash"
            return if (quality != null) "$base/${quality}p" else base
        }

    fun urlOn(host: String): String {
        val suffix = if (query.isNotEmpty()) "?$query" else ""
        return "https://$host$path$suffix"
    }

    val fallbackTitle: String
        get() = "kodik-$videoId"
}

data class PlayerPayload(
    val mediaType: String,
    val videoId: String,
    val contentHash: String
) {
    fun asForm(): Map<String, String> {
        return mapOf(
            "type" to mediaType,
            "id" to videoId,
            "hash" to contentHash,
            "bad_user" to "true",
            "cdn_is_working" to "true"
        )
    }
}

data class Translation(
    val title: String,
    val mediaType: String,
    val mediaId: String,
    val contentHash: String,
    val translationId: String = "",
    val kind: String = "voice",
    val selected: Boolean = false
) {
    val isSubtitles: Boolean get() = kind == "subtitles"

    fun asPayload(): PlayerPayload {
        return PlayerPayload(mediaType, mediaId, contentHash)
    }
}

data class PlayerPage(
    val payload: PlayerPayload,
    val playerJsPath: String,
    val title: String? = null,
    val urlParams: Map<String, String> = emptyMap(),
    val translations: List<Translation> = emptyList(),
    val currentTranslation: Translation? = null
) {
    fun signedForm(targetPayload: PlayerPayload): Map<String, String> {
        val fields = targetPayload.asForm().toMutableMap()
        for (name in listOf("d", "d_sign", "pd", "pd_sign")) {
            val value = urlParams[name]
            if (!value.isNullOrEmpty()) {
                fields[name] = value
            }
        }
        val rawRef = urlParams["ref"].orEmpty()
        val ref = try {
            URLDecoder.decode(rawRef, StandardCharsets.UTF_8.name()).trim()
        } catch (_: Exception) {
            rawRef.trim()
        }
        if (ref.isNotEmpty()) {
            fields["ref"] = ref
            val refSign = urlParams["ref_sign"]
            if (!refSign.isNullOrEmpty()) {
                fields["ref_sign"] = refSign
            }
        }
        return fields
    }
}

data class StreamVariant(
    val quality: Int,
    val url: String,
    val kind: String = "hls",
    val directMp4: String? = null
) {
    val label: String get() = "${quality}p"
}

data class ResolvedVideo(
    val title: String,
    val variants: List<StreamVariant>,
    val translations: List<Translation> = emptyList(),
    val translation: Translation? = null,
    val defaultQuality: Int? = null,
    val warnings: List<String> = emptyList()
) {
    val best: StreamVariant
        get() = variants.firstOrNull() ?: throw NoSuchElementException("no variants available")

    fun pick(quality: Int?): StreamVariant {
        if (variants.isEmpty()) throw NoSuchElementException("no variants available")
        if (quality == null) return best
        val exact = variants.firstOrNull { it.quality == quality }
        if (exact != null) return exact
        val lower = variants.firstOrNull { it.quality < quality }
        if (lower != null) return lower
        return variants.last()
    }
}

enum class DownloadStatus {
    QUEUED,
    DOWNLOADING,
    ASSEMBLING,
    FINISHED,
    FAILED,
    CANCELLED
}

data class DownloadItem(
    val id: String,
    val title: String,
    val fileName: String,
    val url: String,
    val quality: Int,
    val isMp4: Boolean,
    var status: DownloadStatus = DownloadStatus.QUEUED,
    var progress: Float = 0f,
    var downloadedBytes: Long = 0L,
    var totalBytes: Long? = null,
    var speedBytesPerSec: Long = 0L,
    var etaSeconds: Long? = null,
    var savedPath: String? = null,
    var contentUri: String? = null,
    var errorMessage: String? = null
) {
    val isFinished: Boolean get() = status == DownloadStatus.FINISHED
    val isTerminal: Boolean get() = status == DownloadStatus.FINISHED || status == DownloadStatus.FAILED || status == DownloadStatus.CANCELLED
}

data class AppSettings(
    val downloadDir: String,
    val language: String = "auto",
    val theme: String = "auto",
    val concurrentDownloads: Int = 3,
    val preferMp4: Boolean = false
)

data class HistoryItem(
    val id: String,
    val title: String,
    val fileName: String,
    val url: String,
    val quality: Int,
    val translation: String? = null,
    val isMp4: Boolean = false,
    var status: DownloadStatus = DownloadStatus.FINISHED,
    var savedPath: String? = null,
    var contentUri: String? = null,
    var fileSize: Long = 0L,
    val timestamp: Long = System.currentTimeMillis(),
    var errorMessage: String? = null
)

data class LibraryItem(
    val id: String,
    val title: String,
    val fileName: String,
    val filePath: String?,
    val contentUri: String?,
    val fileSizeBytes: Long,
    val dateModified: Long,
    val quality: Int? = null,
    val isMp4: Boolean = true
)
