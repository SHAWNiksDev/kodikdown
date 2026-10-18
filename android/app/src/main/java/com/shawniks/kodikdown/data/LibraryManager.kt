package com.shawniks.kodikdown.data

import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import com.shawniks.kodikdown.util.FileUtils
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

object LibraryManager {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _items = MutableStateFlow<List<LibraryItem>>(emptyList())
    val items: StateFlow<List<LibraryItem>> = _items.asStateFlow()

    fun refresh(context: Context, downloadDir: String) {
        scope.launch {
            val list = scanVideos(context, downloadDir)
            _items.value = list
        }
    }

    fun findExisting(safeName: String): LibraryItem? {
        val targetName = if (safeName.endsWith(".mp4", ignoreCase = true)) safeName else "$safeName.mp4"
        return _items.value.firstOrNull {
            it.fileName.equals(targetName, ignoreCase = true) || it.title.equals(safeName, ignoreCase = true)
        }
    }

    suspend fun deleteItem(context: Context, item: LibraryItem): Boolean = withContext(Dispatchers.IO) {
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
            val current = _items.value.toMutableList()
            current.removeAll { it.id == item.id }
            _items.value = current
        }
        success
    }

    private suspend fun scanVideos(context: Context, downloadDir: String): List<LibraryItem> = withContext(Dispatchers.IO) {
        val results = mutableListOf<LibraryItem>()
        val seenPaths = mutableSetOf<String>()

        val historyMap = mutableMapOf<String, HistoryItem>()
        for (item in HistoryManager.items.value) {
            val k1 = item.fileName.lowercase().removeSuffix(".mp4")
            val k2 = item.fileName.lowercase()
            historyMap.putIfAbsent(k1, item)
            historyMap.putIfAbsent(k2, item)
        }

        // 1. Scan via MediaStore (Video collection)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val projection = arrayOf(
                    MediaStore.Video.Media._ID,
                    MediaStore.Video.Media.DISPLAY_NAME,
                    MediaStore.Video.Media.SIZE,
                    MediaStore.Video.Media.DATE_MODIFIED,
                    MediaStore.Video.Media.RELATIVE_PATH,
                    MediaStore.Video.Media.HEIGHT,
                    MediaStore.Video.Media.WIDTH
                )

                val collection = MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
                val cursor = context.contentResolver.query(
                    collection,
                    projection,
                    null,
                    null,
                    "${MediaStore.Video.Media.DATE_MODIFIED} DESC"
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

                        // Check if file is in KodikDown, Movies, or Downloads
                        val isKodikDown = relPath.contains("KodikDown", ignoreCase = true) ||
                                relPath.contains("Movies", ignoreCase = true) ||
                                relPath.contains("Download", ignoreCase = true) ||
                                historyMap.containsKey(name.lowercase().removeSuffix(".mp4")) ||
                                historyMap.containsKey(name.lowercase())

                        if (isKodikDown && (name.endsWith(".mp4", ignoreCase = true) || name.endsWith(".mkv", ignoreCase = true))) {
                            val contentUri = ContentUris.withAppendedId(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, id)
                            val historyMatch = historyMap[name.lowercase().removeSuffix(".mp4")] ?: historyMap[name.lowercase()]
                            val title = historyMatch?.title ?: name.removeSuffix(".mp4").removeSuffix(".mkv")
                            val quality = (if (height > 0) height else historyMatch?.quality)?.takeIf { it > 0 }

                            val displayPath = "/storage/emulated/0/$relPath$name"
                            seenPaths.add(displayPath)
                            seenPaths.add(name.lowercase())

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
                                    isMp4 = name.endsWith(".mp4", ignoreCase = true)
                                )
                            )
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w("LibraryManager", "Error querying MediaStore", e)
            }
        }

        // 2. Scan physical folders (downloadDir and Movies/KodikDown)
        val scanDirs = listOfNotNull(
            File(downloadDir).takeIf { it.exists() && it.isDirectory },
            File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES), "KodikDown").takeIf { it.exists() },
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES).takeIf { it.exists() },
            File(context.filesDir, "downloads").takeIf { it.exists() }
        ).distinctBy { it.absolutePath }

        for (dir in scanDirs) {
            val files = dir.listFiles { f ->
                f.isFile && (f.name.endsWith(".mp4", ignoreCase = true) || f.name.endsWith(".mkv", ignoreCase = true)) && !f.name.endsWith(".part")
            } ?: continue

            for (file in files) {
                if (seenPaths.contains(file.absolutePath) || seenPaths.contains(file.name.lowercase())) continue
                seenPaths.add(file.absolutePath)
                seenPaths.add(file.name.lowercase())

                val historyMatch = historyMap[file.name.lowercase().removeSuffix(".mp4")] ?: historyMap[file.name.lowercase()]
                val title = historyMatch?.title ?: file.name.removeSuffix(".mp4").removeSuffix(".mkv")

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
                        isMp4 = file.name.endsWith(".mp4", ignoreCase = true)
                    )
                )
            }
        }

        results.sortedByDescending { it.dateModified }
    }
}
