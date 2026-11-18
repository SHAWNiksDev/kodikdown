package com.shawniks.kodikdown.data

import android.content.Context
import android.util.AtomicFile
import android.util.Log
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

object HistoryManager {
    private const val FILE_NAME = "download_history.json"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _items = MutableStateFlow<List<HistoryItem>>(emptyList())
    val items: StateFlow<List<HistoryItem>> = _items.asStateFlow()

    private data class Command(
        val context: Context,
        val transform: ((List<HistoryItem>) -> List<HistoryItem>)?,
    )

    private val commands = Channel<Command>(Channel.UNLIMITED)
    private var initialized = false

    init {
        scope.launch {
            for (command in commands) {
                if (!initialized) {
                    loadFromDisk(command.context)
                    LibraryManager.migrate(command.context, _items.value)
                    initialized = true
                }
                command.transform?.let { transform ->
                    val updated = transform(_items.value)
                    _items.value = updated
                    saveToDisk(command.context, updated)
                }
            }
        }
    }

    fun init(context: Context) {
        commands.trySend(Command(context.applicationContext, null))
    }

    private fun mutate(context: Context, transform: (List<HistoryItem>) -> List<HistoryItem>) {
        commands.trySend(Command(context.applicationContext, transform))
    }

    fun recordFromDownload(
        context: Context,
        downloadItem: DownloadItem,
        translationTitle: String? = null,
    ) {
        val entry =
            HistoryItem(
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
                fileSize =
                    downloadItem.downloadedBytes.takeIf { it > 0 }
                        ?: (downloadItem.totalBytes ?: 0L),
                timestamp = System.currentTimeMillis(),
                errorMessage = downloadItem.errorMessage,
                sourceInput = downloadItem.sourceInput,
                retryInput = downloadItem.retryInput,
                series = downloadItem.series,
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
        error: String? = null,
    ) {
        mutate(context) { list ->
            list.map { item ->
                if (item.id != id) item
                else
                    item.copy(
                        status = status,
                        savedPath = savedPath ?: item.savedPath,
                        contentUri = contentUri ?: item.contentUri,
                        fileSize = fileSize ?: item.fileSize,
                        errorMessage = error,
                    )
            }
        }
    }

    fun recordOrUpdate(context: Context, item: HistoryItem) {
        mutate(context) { list ->
            val old = list.firstOrNull { it.id == item.id }
            val entry =
                item.copy(
                    translation = item.translation ?: old?.translation,
                    sourceInput = item.sourceInput ?: old?.sourceInput,
                    timestamp = old?.timestamp ?: item.timestamp,
                )
            if (old == null) listOf(entry) + list
            else list.map { if (it.id == entry.id) entry else it }
        }
    }

    fun remove(context: Context, id: String) {
        mutate(context) { list -> list.filterNot { it.id == id && !com.shawniks.kodikdown.downloader.DownloadManager.isActive(it.id) } }
    }

    fun clear(context: Context) {
        mutate(context) { list -> list.filter { com.shawniks.kodikdown.downloader.DownloadManager.isActive(it.id) } }
    }

    fun findCompleted(url: String, fileName: String): HistoryItem? {
        return _items.value.firstOrNull {
            it.status == DownloadStatus.FINISHED &&
                (it.url == url || it.fileName.equals(fileName, ignoreCase = true))
        }
    }

    private fun loadFromDisk(context: Context) {
        try {
            val file = AtomicFile(File(context.filesDir, FILE_NAME))
            if (!file.baseFile.exists() && !File(context.filesDir, "$FILE_NAME.bak").exists())
                return

            val jsonStr = file.openRead().bufferedReader().use { it.readText() }
            val array = JSONArray(jsonStr)
            val list = mutableListOf<HistoryItem>()

            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                val statusStr = obj.optString("status", DownloadStatus.FINISHED.name)
                val status =
                    try {
                        DownloadStatus.valueOf(statusStr)
                    } catch (_: Exception) {
                        DownloadStatus.FAILED
                    }

                val translation =
                    if (obj.has("translation") && !obj.isNull("translation"))
                        obj.getString("translation")
                    else null
                val savedPath =
                    if (obj.has("savedPath") && !obj.isNull("savedPath")) obj.getString("savedPath")
                    else null
                val contentUri =
                    if (obj.has("contentUri") && !obj.isNull("contentUri"))
                        obj.getString("contentUri")
                    else null
                val errorMessage =
                    if (obj.has("errorMessage") && !obj.isNull("errorMessage"))
                        obj.getString("errorMessage")
                    else null

                list.add(
                    HistoryItem(
                        id = obj.getString("id"),
                        title = obj.getString("title"),
                        fileName = obj.getString("fileName"),
                        url = obj.getString("url"),
                        quality = obj.getInt("quality"),
                        sourceInput = if (obj.has("sourceInput") && !obj.isNull("sourceInput")) obj.getString("sourceInput") else null,
                        retryInput = obj.optString("retryInput").takeIf { it.isNotBlank() },
                        series = obj.optString("series").takeIf { it.isNotBlank() },
                        translation = translation,
                        isMp4 = obj.optBoolean("isMp4", false),
                        status =
                            if (
                                status in
                                    setOf(
                                        DownloadStatus.QUEUED,
                                        DownloadStatus.DOWNLOADING,
                                        DownloadStatus.ASSEMBLING,
                                    )
                            )
                                DownloadStatus.FAILED
                            else status,
                        savedPath = savedPath,
                        contentUri = contentUri,
                        fileSize = obj.optLong("fileSize", 0L),
                        timestamp = obj.optLong("timestamp", System.currentTimeMillis()),
                        errorMessage =
                            if (
                                status in
                                    setOf(
                                        DownloadStatus.QUEUED,
                                        DownloadStatus.DOWNLOADING,
                                        DownloadStatus.ASSEMBLING,
                                    )
                            )
                                "Download interrupted; retry to start again"
                            else errorMessage,
                    )
                )
            }
            _items.value = list
        } catch (e: Exception) {
            Log.e("HistoryManager", "Failed to load history from disk", e)
        }
    }

    private fun saveToDisk(context: Context, list: List<HistoryItem>) {
        try {
            val array = JSONArray()
            for (item in list) {
                val obj =
                    JSONObject().apply {
                        put("id", item.id)
                        put("title", item.title)
                        put("fileName", item.fileName)
                        put("url", item.url)
                        put("sourceInput", item.sourceInput)
                        put("retryInput", item.retryInput)
                        put("series", item.series)
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
            val file = AtomicFile(File(context.filesDir, FILE_NAME))
            val stream = file.startWrite()
            try {
                stream.write(array.toString(2).toByteArray(Charsets.UTF_8))
                file.finishWrite(stream)
            } catch (e: Exception) {
                file.failWrite(stream)
                throw e
            }
        } catch (e: Exception) {
            Log.e("HistoryManager", "Failed to save history to disk", e)
        }
    }
}
