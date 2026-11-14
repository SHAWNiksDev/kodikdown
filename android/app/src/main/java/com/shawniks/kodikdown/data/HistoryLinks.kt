package com.shawniks.kodikdown.data

import com.shawniks.kodikdown.kodik.KodikParser

object HistoryLinks {
    fun copySource(item: HistoryItem): String? {
        item.sourceInput?.takeIf { it.isNotBlank() }?.let { return it }
        // Older records sometimes held player URLs. A CDN URL cannot recover the original input.
        return item.url.takeIf { runCatching { KodikParser.extractEmbed(it) }.isSuccess }
    }
}
