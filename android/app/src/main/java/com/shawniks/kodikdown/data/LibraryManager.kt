package com.shawniks.kodikdown.data

import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.os.Build
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.util.Log
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

object LibraryManager {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _items = MutableStateFlow<List<LibraryItem>>(emptyList())
    val items: StateFlow<List<LibraryItem>> = _items.asStateFlow()

    private val refreshGeneration = AtomicInteger()

    fun refresh(context: Context, downloadDir: String) {
        val generation = refreshGeneration.incrementAndGet()
        val app = context.applicationContext
        scope.launch {
            val list = scanVideos(app, downloadDir)
            if (generation == refreshGeneration.get()) {
                _items.value = list
                MediaFiles.requestRefresh()
            }
        }
    }

    fun pruneUnavailable(available: (String?, String?) -> Boolean) {
        _items.update { list -> list.filter { available(it.filePath, it.contentUri) } }
    }

    fun findExisting(safeName: String): LibraryItem? {
        val targetName =
            if (safeName.endsWith(".mp4", ignoreCase = true)) safeName else "$safeName.mp4"
        return _items.value.firstOrNull {
            it.fileName.equals(targetName, ignoreCase = true) ||
                it.title.equals(safeName, ignoreCase = true)
        }
    }

    suspend fun deleteItem(context: Context, item: LibraryItem): Boolean =
        withContext(Dispatchers.IO) {
            if (MediaFiles.isPending(item.filePath) || MediaFiles.isPending(item.contentUri)) return@withContext false
            var success = false

            // 1. Delete content uri
            if (!item.contentUri.isNullOrEmpty()) {
                success = FileUtils.deleteFile(context, item.contentUri)
            }

            // 2. Delete file path
            if (!item.filePath.isNullOrEmpty()) {
                val file = File(item.filePath)
                if (file.exists()) {
                    val fDeleted = file.delete()
                    success = success || fDeleted
                }
            }

            if (success) {
                refreshGeneration.incrementAndGet()
                _items.update { list -> list.filterNot { it.id == item.id } }
            }
            MediaFiles.requestRefresh()
            success
        }

    private suspend fun scanVideos(context: Context, downloadDir: String): List<LibraryItem> =
        withContext(Dispatchers.IO) {
            val results = mutableListOf<LibraryItem>()
            val seenPaths = mutableSetOf<String>()

            val historyMap = mutableMapOf<String, HistoryItem>()
            for (item in HistoryManager.items.value) {
                val k1 = item.fileName.lowercase().removeSuffix(".mp4")
                val k2 = item.fileName.lowercase()
                historyMap.putIfAbsent(k1, item)
                historyMap.putIfAbsent(k2, item)
            }

            if (downloadDir.startsWith("content://")) {
                try {
                    val tree = Uri.parse(downloadDir)
                    val children =
                        DocumentsContract.buildChildDocumentsUriUsingTree(
                            tree,
                            DocumentsContract.getTreeDocumentId(tree),
                        )
                    val columns =
                        arrayOf(
                            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                            DocumentsContract.Document.COLUMN_SIZE,
                            DocumentsContract.Document.COLUMN_LAST_MODIFIED,
                            DocumentsContract.Document.COLUMN_MIME_TYPE,
                        )
                    context.contentResolver.query(children, columns, null, null, null)?.use { cursor
                        ->
                        while (cursor.moveToNext()) {
                            val id = cursor.getString(0)
                            val name = cursor.getString(1) ?: continue
                            if (!cursor.getString(4).orEmpty().startsWith("video/")) continue
                            val uri =
                                DocumentsContract.buildDocumentUriUsingTree(tree, id).toString()
                            if (MediaFiles.isPending(uri)) continue
                            val history =
                                HistoryManager.items.value.firstOrNull { it.contentUri == uri }
                            results.add(
                                LibraryItem(
                                    uri,
                                    history?.title ?: name.substringBeforeLast('.'),
                                    name,
                                    null,
                                    uri,
                                    cursor.getLong(2),
                                    cursor.getLong(3),
                                    history?.quality,
                                    name.endsWith(".mp4", true),
                                )
                            )
                        }
                    }
                } catch (e: Exception) {
                    Log.w("LibraryManager", "Could not read selected folder", e)
                }
                return@withContext results.sortedByDescending { it.dateModified }
            }
            val selectedDirectory =
                runCatching { FileUtils.publicDirectory(downloadDir).trimEnd('/') + "/" }
                    .getOrNull()

            // 1. Scan via MediaStore (Video collection)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                try {
                    val projection =
                        arrayOf(
                            MediaStore.Video.Media._ID,
                            MediaStore.Video.Media.DISPLAY_NAME,
                            MediaStore.Video.Media.SIZE,
                            MediaStore.Video.Media.DATE_MODIFIED,
                            MediaStore.Video.Media.RELATIVE_PATH,
                            MediaStore.Video.Media.HEIGHT,
                            MediaStore.Video.Media.WIDTH,
                        )

                    val collection =
                        MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
                    val cursor =
                        context.contentResolver.query(
                            collection,
                            projection,
                            if (selectedDirectory != null) "is_pending = 0 AND relative_path = ?" else "is_pending = 0",
                            selectedDirectory?.let { arrayOf(it) },
                            "${MediaStore.Video.Media.DATE_MODIFIED} DESC",
                        )

                    cursor?.use { c ->
                        val idCol = c.getColumnIndexOrThrow(MediaStore.Video.Media._ID)
                        val nameCol = c.getColumnIndexOrThrow(MediaStore.Video.Media.DISPLAY_NAME)
                        val sizeCol = c.getColumnIndexOrThrow(MediaStore.Video.Media.SIZE)
                        val dateCol = c.getColumnIndexOrThrow(MediaStore.Video.Media.DATE_MODIFIED)
                        val relCol = c.getColumnIndexOrThrow(MediaStore.Video.Media.RELATIVE_PATH)
                        val heightCol = c.getColumnIndex(MediaStore.Video.Media.HEIGHT)

                        while (c.moveToNext()) {
                            val id = c.getLong(idCol)
                            val name = c.getString(nameCol) ?: continue
                            val size = c.getLong(sizeCol)
                            val dateSec = c.getLong(dateCol)
                            val relPath = c.getString(relCol) ?: ""
                            val height = if (heightCol >= 0) c.getInt(heightCol) else 0

                            // Scope the library to the selected directory; unrelated personal
                            // videos in Movies/Downloads must not appear as app downloads.
                            val isKodikDown =
                                selectedDirectory != null &&
                                    relPath.trimEnd('/') + "/" == selectedDirectory

                            if (
                                isKodikDown &&
                                    (name.endsWith(".mp4", ignoreCase = true) ||
                                        name.endsWith(".mkv", ignoreCase = true))
                            ) {
                                val contentUri =
                                    ContentUris.withAppendedId(
                                        MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                                        id,
                                    )
                                val historyMatch =
                                    historyMap[name.lowercase().removeSuffix(".mp4")]
                                        ?: historyMap[name.lowercase()]
                                val title =
                                    historyMatch?.title
                                        ?: name.removeSuffix(".mp4").removeSuffix(".mkv")
                                val quality =
                                    (if (height > 0) height else historyMatch?.quality)?.takeIf {
                                        it > 0
                                    }

                                val displayPath = "/storage/emulated/0/$relPath$name"
                                seenPaths.add(displayPath)

                                results.add(
                                    LibraryItem(
                                        id = id.toString(),
                                        title = title,
                                        fileName = name,
                                        filePath = displayPath,
                                        contentUri = contentUri.toString(),
                                        fileSizeBytes = size,
                                        dateModified = dateSec * 1000L,
                                        quality = quality,
                                        isMp4 = name.endsWith(".mp4", ignoreCase = true),
                                    )
                                )
                            }
                        }
                    }
                } catch (e: Exception) {
                    Log.w("LibraryManager", "Error querying MediaStore", e)
                }

                // Also query MediaStore.Downloads if download folder is within Download/
                if (selectedDirectory != null && selectedDirectory.startsWith("Download/")) {
                    try {
                        val projection =
                            arrayOf(
                                MediaStore.Downloads._ID,
                                MediaStore.Downloads.DISPLAY_NAME,
                                MediaStore.Downloads.SIZE,
                                MediaStore.Downloads.DATE_MODIFIED,
                                MediaStore.Downloads.RELATIVE_PATH,
                                MediaStore.Downloads.MIME_TYPE,
                            )
                        val collection =
                            MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL)
                        val cursor =
                            context.contentResolver.query(
                                collection,
                                projection,
                                "is_pending = 0 AND relative_path = ?",
                                arrayOf(selectedDirectory),
                                "${MediaStore.Downloads.DATE_MODIFIED} DESC",
                            )
                        cursor?.use { c ->
                            val idCol = c.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                            val nameCol = c.getColumnIndexOrThrow(MediaStore.Downloads.DISPLAY_NAME)
                            val sizeCol = c.getColumnIndexOrThrow(MediaStore.Downloads.SIZE)
                            val dateCol = c.getColumnIndexOrThrow(MediaStore.Downloads.DATE_MODIFIED)
                            val relCol = c.getColumnIndexOrThrow(MediaStore.Downloads.RELATIVE_PATH)
                            val mimeCol = c.getColumnIndex(MediaStore.Downloads.MIME_TYPE)

                            while (c.moveToNext()) {
                                val id = c.getLong(idCol)
                                val name = c.getString(nameCol) ?: continue
                                val size = c.getLong(sizeCol)
                                val dateSec = c.getLong(dateCol)
                                val relPath = c.getString(relCol) ?: ""
                                val mime = if (mimeCol >= 0) c.getString(mimeCol).orEmpty() else ""

                                val isKodikDown = relPath.trimEnd('/') + "/" == selectedDirectory
                                if (
                                    isKodikDown &&
                                        (mime.startsWith("video/") ||
                                            name.endsWith(".mp4", ignoreCase = true) ||
                                            name.endsWith(".mkv", ignoreCase = true))
                                ) {
                                    val displayPath = "/storage/emulated/0/$relPath$name"
                                    if (seenPaths.add(displayPath)) {
                                        val contentUri =
                                            ContentUris.withAppendedId(
                                                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                                                id,
                                            )
                                        val historyMatch =
                                            historyMap[name.lowercase().removeSuffix(".mp4")]
                                                ?: historyMap[name.lowercase()]
                                        val title =
                                            historyMatch?.title
                                                ?: name.removeSuffix(".mp4").removeSuffix(".mkv")
                                        val quality = historyMatch?.quality?.takeIf { it > 0 }

                                        results.add(
                                            LibraryItem(
                                                id = "dl_$id",
                                                title = title,
                                                fileName = name,
                                                filePath = displayPath,
                                                contentUri = contentUri.toString(),
                                                fileSizeBytes = size,
                                                dateModified = dateSec * 1000L,
                                                quality = quality,
                                                isMp4 = name.endsWith(".mp4", ignoreCase = true),
                                            )
                                        )
                                    }
                                }
                            }
                        }
                    } catch (e: Exception) {
                        Log.w("LibraryManager", "Error querying MediaStore Downloads", e)
                    }
                }
            }

            // 2. Scan physical folders (downloadDir and Movies/KodikDown)
            val scanDirs = listOfNotNull(File(downloadDir).takeIf { it.exists() && it.isDirectory })

            for (dir in scanDirs) {
                val files =
                    dir.listFiles { f ->
                        f.isFile && f.length() > 0 && !MediaFiles.isPending(f.absolutePath) &&
                            (f.name.endsWith(".mp4", ignoreCase = true) ||
                                f.name.endsWith(".mkv", ignoreCase = true)) &&
                            !f.name.endsWith(".part")
                    } ?: continue

                for (file in files) {
                    if (seenPaths.contains(file.absolutePath)) continue
                    seenPaths.add(file.absolutePath)

                    val historyMatch =
                        historyMap[file.name.lowercase().removeSuffix(".mp4")]
                            ?: historyMap[file.name.lowercase()]
                    val title =
                        historyMatch?.title ?: file.name.removeSuffix(".mp4").removeSuffix(".mkv")

                    results.add(
                        LibraryItem(
                            id = file.absolutePath.hashCode().toString(),
                            title = title,
                            fileName = file.name,
                            filePath = file.absolutePath,
                            contentUri = historyMatch?.contentUri,
                            fileSizeBytes = file.length(),
                            dateModified = file.lastModified(),
                            quality = historyMatch?.quality,
                            isMp4 = file.name.endsWith(".mp4", ignoreCase = true),
                        )
                    )
                }
            }

            results.sortedByDescending { it.dateModified }
        }
}
