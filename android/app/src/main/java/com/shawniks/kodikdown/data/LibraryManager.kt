package com.shawniks.kodikdown.data

import android.content.Context
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

object LibraryManager {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val generation = AtomicInteger()
    private val _items = MutableStateFlow<List<LibraryItem>>(emptyList())
    val items: StateFlow<List<LibraryItem>> = _items.asStateFlow()

    private fun preferences(context: Context) =
        context.getSharedPreferences("download_library", Context.MODE_PRIVATE)

    @Synchronized
    fun migrate(context: Context, history: List<HistoryItem>) {
        val prefs = preferences(context)
        if (prefs.contains("entries")) return
        write(context, history.filter { it.status == DownloadStatus.FINISHED }.mapNotNull {
            item(it.id, it.title, it.fileName, it.savedPath, it.contentUri, it.fileSize, it.timestamp, it.quality, it.series)
        })
        refresh(context)
    }

    @Synchronized
    fun record(context: Context, download: DownloadItem) {
        val entry = item(download.id, download.title, download.fileName, download.savedPath,
            download.contentUri, download.downloadedBytes, System.currentTimeMillis(), download.quality, download.series) ?: return
        val existing = read(context)
        write(context, listOf(entry) + existing.filterNot {
            it.id == entry.id || entry.filePath != null && it.filePath == entry.filePath ||
                entry.contentUri != null && it.contentUri == entry.contentUri
        })
        refresh(context)
    }

    fun refresh(context: Context, @Suppress("UNUSED_PARAMETER") downloadDir: String = "") {
        val current = generation.incrementAndGet()
        val app = context.applicationContext
        scope.launch {
            val items = read(app).filter { MediaFiles.exists(app, it.filePath, it.contentUri) }
            if (current == generation.get()) {
                _items.value = items
                MediaFiles.requestRefresh()
            }
        }
    }

    fun pruneUnavailable(available: (String?, String?) -> Boolean) {
        _items.update { list -> list.filter { available(it.filePath, it.contentUri) } }
    }

    fun findExisting(safeName: String): LibraryItem? {
        val name = if (safeName.endsWith(".mp4", true)) safeName else "$safeName.mp4"
        return _items.value.firstOrNull { it.fileName.equals(name, true) || it.title.equals(safeName, true) }
    }

    suspend fun deleteItem(context: Context, item: LibraryItem): Boolean = withContext(Dispatchers.IO) {
        if (MediaFiles.isPending(item.filePath) || MediaFiles.isPending(item.contentUri)) return@withContext false
        val success = item.contentUri?.let { FileUtils.deleteFile(context, it) } == true ||
            item.filePath?.let { FileUtils.deleteFile(context, it) } == true
        if (success) {
            synchronized(this@LibraryManager) {
                write(context, read(context).filterNot { it.id == item.id })
            }
            refresh(context)
        }
        success
    }

    private fun item(id: String, title: String, name: String, path: String?, uri: String?,
        size: Long, time: Long, quality: Int, series: String?): LibraryItem? {
        if (path.isNullOrBlank() && uri.isNullOrBlank()) return null
        val fileName = path?.takeUnless { it.startsWith("content://") }?.let { File(it).name }
            ?: "${name.removeSuffix(".mp4")}.mp4"
        return LibraryItem(id, title, fileName, path, uri, size, time, quality.takeIf { it > 0 }, series = series)
    }

    private fun read(context: Context): List<LibraryItem> {
        val data = runCatching { JSONArray(preferences(context).getString("entries", "[]")) }
            .getOrElse { return emptyList() }
        return (0 until data.length()).mapNotNull { index ->
            val entry = data.optJSONObject(index) ?: return@mapNotNull null
            item(entry.optString("id"), entry.optString("title"), entry.optString("name"),
                entry.optString("path").takeIf { it.isNotBlank() },
                entry.optString("uri").takeIf { it.startsWith("content://") || it.startsWith("file://") },
                entry.optLong("size"), entry.optLong("time"), entry.optInt("quality"),
                entry.optString("series").takeIf { it.isNotBlank() })
        }
    }

    private fun write(context: Context, items: List<LibraryItem>) {
        val data = JSONArray()
        items.forEach {
            data.put(JSONObject().put("id", it.id).put("title", it.title).put("name", it.fileName)
                .put("path", it.filePath).put("uri", it.contentUri).put("size", it.fileSizeBytes)
                .put("time", it.dateModified).put("quality", it.quality).put("series", it.series))
        }
        preferences(context).edit().putString("entries", data.toString()).apply()
    }
}
