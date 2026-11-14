package com.shawniks.kodikdown.data

import java.io.IOException

/** Obtain fresh signed URLs while retaining the original quality and voice track. */
object HistoryRetry {
    data class Selection(val variant: StreamVariant, val variants: List<StreamVariant>,
        val translation: String?, val source: String?)

    suspend fun resolve(item: HistoryItem,
        resolver: suspend (String, Translation?) -> ResolvedVideo): Selection {
        val source = HistoryLinks.copySource(item)
        if (source == null) {
            // Old history has no player URL. Its stream is the only recoverable reference.
            val variant = StreamVariant(item.quality, item.url, if (item.isMp4) "mp4" else "hls",
                if (item.isMp4) item.url else null)
            return Selection(variant, listOf(variant), item.translation, null)
        }
        var video = resolver(source, null)
        if (!item.translation.isNullOrBlank() && video.translation?.title != item.translation) {
            val translation = video.translations.firstOrNull { it.title == item.translation }
                ?: throw IOException("The original translation is no longer available")
            video = resolver(source, translation)
        }
        return Selection(video.pick(item.quality), video.variants, video.translation?.title, source)
    }
}
