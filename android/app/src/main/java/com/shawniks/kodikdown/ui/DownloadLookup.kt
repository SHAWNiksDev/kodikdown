package com.shawniks.kodikdown.ui

import androidx.lifecycle.ViewModel
import com.shawniks.kodikdown.data.HistoryItem
import com.shawniks.kodikdown.data.HistoryRetry
import com.shawniks.kodikdown.data.ResolvedVideo
import com.shawniks.kodikdown.data.StreamVariant
import com.shawniks.kodikdown.data.Translation
import com.shawniks.kodikdown.kodik.CatalogClient
import com.shawniks.kodikdown.kodik.KodikClient
import java.io.IOException

internal class DownloadLookup : ViewModel() {
    private val kodik = KodikClient()
    private val catalogs = CatalogClient(kodik)

    var resolved: ResolvedVideo? = null
    var resolvedUrl = ""
    var selectedVariant: StreamVariant? = null
    var selectedTranslation: Translation? = null
    var nameEdited = false

    suspend fun catalog(url: String) = catalogs.lookup(url)

    suspend fun poster(url: String): ByteArray? = try {
        catalogs.poster(url)
    } catch (_: IOException) {
        null
    }

    suspend fun resolve(url: String, translation: Translation? = null): ResolvedVideo =
        if (translation == null) catalogs.resolve(url) else kodik.resolve(url, translation)

    suspend fun retry(item: HistoryItem): HistoryRetry.Selection = HistoryRetry.resolve(item, ::resolve)
}
