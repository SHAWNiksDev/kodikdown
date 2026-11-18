package com.shawniks.kodikdown.data

import com.shawniks.kodikdown.kodik.KodikParser
import com.shawniks.kodikdown.kodik.CatalogClient

object HistoryLinks {
    fun copySource(item: HistoryItem): String? {
        item.sourceInput?.takeIf { it.isNotBlank() }?.let {
            return CatalogClient.normalize(it).substringBefore("#kd_episode=")
        }
        // Older records sometimes held player URLs. A CDN URL cannot recover the original input.
        return item.url.takeIf { runCatching { KodikParser.extractEmbed(it) }.isSuccess }
    }
}
