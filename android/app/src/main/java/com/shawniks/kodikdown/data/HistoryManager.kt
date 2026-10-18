package com.shawniks.kodikdown.data

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

object HistoryManager {
    private const val FILE_NAME = "download_history.json"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _items = MutableStateFlow<List<HistoryItem>>(emptyList())
    val items: StateFlow<List<HistoryItem>> = _items.asStateFlow()

    private var initialized = false

    fun init(context: Context) {
        if (initialized) return
        initialized = true
        scope.launch {
            loadFromDisk(context)
        }
    }

    fun recordFromDownload(
        context: Context,
        downloadItem: DownloadItem,
        translationTitle: String? = null
    ) {
        val entry = HistoryItem(
            id = downloadItem.id,
            title = downloadItem.title,
            fileName = downloadItem.fileName,
            url = downloadItem.url,
            quality = downloadItem.quality,
            translation = translationTitle,
            isMp4 = downloadItem.isMp4,
            status = downloadItem.status,
            savedPath = downloadItem.savedPath,
            contentUri = downloadItem.contentUri,
            fileSize = downloadItem.downloadedBytes.takeIf { it > 0 } ?: (downloadItem.totalBytes ?: 0L),
            timestamp = System.currentTimeMillis(),
            errorMessage = downloadItem.errorMessage
        )
        recordOrUpdate(context, entry)
    }

    fun updateStatus(
        context: Context,
        id: String,
        status: DownloadStatus,
        savedPath: String? = null,
        contentUri: String? = null,
        fileSize: Long? = null,
        error: String? = null
    ) {
        val currentList = _items.value.toMutableList()
        val index = currentList.indexOfFirst { it.id == id }
        if (index != -1) {
            val item = currentList[index].copy(
                status = status,
                savedPath = savedPath ?: currentList[index].savedPath,
                contentUri = contentUri ?: currentList[index].contentUri,
                fileSize = fileSize ?: currentList[index].fileSize,
                errorMessage = error ?: currentList[index].errorMessage
            )
            currentList[index] = item
            _items.value = currentList
            saveToDisk(context, currentList)
        }
    }

    fun recordOrUpdate(context: Context, item: HistoryItem) {
        val currentList = _items.value.toMutableList()
        val index = currentList.indexOfFirst { it.id == item.id }
        if (index != -1) {
            currentList[index] = item
        } else {
            currentList.add(0, item)
        }
        _items.value = currentList
        saveToDisk(context, currentList)
    }

    fun remove(context: Context, id: String) {
        val currentList = _items.value.toMutableList()
        currentList.removeAll { it.id == id }
        _items.value = currentList
        saveToDisk(context, currentList)
    }

    fun clear(context: Context) {
        _items.value = emptyList()
        saveToDisk(context, emptyList())
    }

    fun findCompleted(url: String, fileName: String): HistoryItem? {
        return _items.value.firstOrNull {
            it.status == DownloadStatus.FINISHED && (it.url == url || it.fileName.equals(fileName, ignoreCase = true))
        }
    }

    private fun loadFromDisk(context: Context) {
        try {
            val file = File(context.filesDir, FILE_NAME)
            if (!file.exists()) return

            val jsonStr = file.readText()
            val array = JSONArray(jsonStr)
            val list = mutableListOf<HistoryItem>()

            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                val statusStr = obj.optString("status", DownloadStatus.FINISHED.name)
                val status = try {
                    DownloadStatus.valueOf(statusStr)
                } catch (_: Exception) {
                    DownloadStatus.FINISHED
                }

                val translation = if (obj.has("translation") && !obj.isNull("translation")) obj.getString("translation") else null
                val savedPath = if (obj.has("savedPath") && !obj.isNull("savedPath")) obj.getString("savedPath") else null
                val contentUri = if (obj.has("contentUri") && !obj.isNull("contentUri")) obj.getString("contentUri") else null
                val errorMessage = if (obj.has("errorMessage") && !obj.isNull("errorMessage")) obj.getString("errorMessage") else null

                list.add(
                    HistoryItem(
                        id = obj.getString("id"),
                        title = obj.getString("title"),
                        fileName = obj.getString("fileName"),
                        url = obj.getString("url"),
                        quality = obj.getInt("quality"),
                        translation = translation,
                        isMp4 = obj.optBoolean("isMp4", false),
                        status = status,
                        savedPath = savedPath,
                        contentUri = contentUri,
                        fileSize = obj.optLong("fileSize", 0L),
                        timestamp = obj.optLong("timestamp", System.currentTimeMillis()),
                        errorMessage = errorMessage
                    )
                )
            }
            _items.value = list
        } catch (e: Exception) {
            Log.e("HistoryManager", "Failed to load history from disk", e)
        }
    }

    private fun saveToDisk(context: Context, list: List<HistoryItem>) {
        scope.launch {
            try {
                val array = JSONArray()
                for (item in list) {
                    val obj = JSONObject().apply {
                        put("id", item.id)
                        put("title", item.title)
                        put("fileName", item.fileName)
                        put("url", item.url)
                        put("quality", item.quality)
                        if (item.translation != null) put("translation", item.translation)
                        put("isMp4", item.isMp4)
                        put("status", item.status.name)
                        if (item.savedPath != null) put("savedPath", item.savedPath)
                        if (item.contentUri != null) put("contentUri", item.contentUri)
                        put("fileSize", item.fileSize)
                        put("timestamp", item.timestamp)
                        if (item.errorMessage != null) put("errorMessage", item.errorMessage)
                    }
                    array.put(obj)
                }
                val file = File(context.filesDir, FILE_NAME)
                file.writeText(array.toString(2))
            } catch (e: Exception) {
                Log.e("HistoryManager", "Failed to save history to disk", e)
            }
        }
    }
}
