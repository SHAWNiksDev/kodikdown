package com.shawniks.kodikdown.util

import android.app.DownloadManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.widget.Toast
import androidx.core.content.FileProvider
import com.shawniks.kodikdown.R
import java.io.File
import java.util.regex.Pattern

object FileUtils {
    private val ILLEGAL_CHARS = Pattern.compile("""[<>:"/\\|?*\x00-\x1f]""")
    private val MEDIA_SUFFIX_RE = Pattern.compile("""\.(mp4|mkv|webm|avi|mov|m4v|flv|wmv|ts)$""", Pattern.CASE_INSENSITIVE)
    private val TEMPLATE_CHARS = Pattern.compile("%")
    private val RESERVED_NAMES = setOf(
        "con", "prn", "aux", "nul",
        "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
        "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"
    )

    fun safeFileName(raw: String, fallback: String = "video"): String {
        var cleaned = ILLEGAL_CHARS.matcher(raw).replaceAll("_").trim(' ', '.')
        cleaned = TEMPLATE_CHARS.matcher(cleaned).replaceAll("_")
        cleaned = cleaned.replace(Regex("\\s+"), " ")
        if (cleaned.length > 120) {
            cleaned = cleaned.substring(0, 120)
        }
        cleaned = MEDIA_SUFFIX_RE.matcher(cleaned).replaceAll("").trim(' ', '.')
        if (cleaned.isEmpty() || cleaned.all { it == '_' }) {
            return fallback
        }
        val base = cleaned.substringBefore('.').trim().lowercase()
        if (RESERVED_NAMES.contains(base)) {
            cleaned = "_$cleaned"
        }
        return cleaned
    }

    /**
     * Saves a completed video into public user storage using MediaStore (Android 10+)
     * or standard filesystem (Android 9 and below), bypassing Scoped Storage write restrictions.
     */
    fun saveToPublicStorage(
        context: Context,
        sourceTempFile: File,
        baseFileName: String,
        targetFolder: String
    ): Pair<String, Uri> {
        val fileName = "$baseFileName.mp4"
        val isMovies = targetFolder.contains("Movie", ignoreCase = true)
        val relativeSubDir = when {
            targetFolder.contains("/storage/emulated/0/") -> {
                val sub = targetFolder.substringAfter("/storage/emulated/0/").trim('/')
                when {
                    sub.startsWith("Download", ignoreCase = true) || sub.startsWith("Movies", ignoreCase = true) || sub.startsWith("DCIM", ignoreCase = true) -> sub
                    isMovies -> "Movies/$sub"
                    else -> "Download/$sub"
                }
            }
            targetFolder.startsWith("Download", ignoreCase = true) -> targetFolder
            targetFolder.startsWith("Movies", ignoreCase = true) -> targetFolder
            isMovies -> "Movies/KodikDown"
            else -> "Download/KodikDown"
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val contentValues = ContentValues().apply {
                put(MediaStore.Video.Media.DISPLAY_NAME, fileName)
                put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                put(MediaStore.Video.Media.RELATIVE_PATH, relativeSubDir)
                put(MediaStore.Video.Media.IS_PENDING, 1)
            }

            val collection = MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            val uri = context.contentResolver.insert(collection, contentValues)
                ?: throw java.io.IOException("Failed to create MediaStore record for $fileName")

            context.contentResolver.openOutputStream(uri).use { out ->
                if (out == null) throw java.io.IOException("Could not open output stream for $uri")
                sourceTempFile.inputStream().use { input ->
                    input.copyTo(out)
                }
            }

            contentValues.clear()
            contentValues.put(MediaStore.Video.Media.IS_PENDING, 0)
            context.contentResolver.update(uri, contentValues, null, null)

            val displayPath = "/storage/emulated/0/$relativeSubDir/$fileName"
            return Pair(displayPath, uri)
        } else {
            // Android 9 and lower: direct file copy
            val publicDir = if (isMovies) {
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES)
            } else {
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            }
            val appDir = File(publicDir, "KodikDown")
            if (!appDir.exists()) appDir.mkdirs()

            var targetFile = File(appDir, fileName)
            var index = 2
            while (targetFile.exists()) {
                targetFile = File(appDir, "$baseFileName ($index).mp4")
                index++
            }

            sourceTempFile.copyTo(targetFile, overwrite = true)
            scanMedia(context, targetFile)

            val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", targetFile)
            return Pair(targetFile.absolutePath, uri)
        }
    }

    fun scanMedia(context: Context, file: File) {
        try {
            MediaScannerConnection.scanFile(
                context.applicationContext,
                arrayOf(file.absolutePath),
                arrayOf("video/mp4"),
                null
            )
        } catch (_: Exception) {}
    }

    /**
     * Opens a folder in the user's preferred file manager.
     */
    fun openFolder(context: Context, targetFolder: String) {
        val isMovies = targetFolder.contains("Movie", ignoreCase = true)
        val relativeSubDir = when {
            targetFolder.contains("/storage/emulated/0/") -> {
                val sub = targetFolder.substringAfter("/storage/emulated/0/").trim('/')
                if (sub.isNotEmpty()) sub else if (isMovies) "Movies/KodikDown" else "Download/KodikDown"
            }
            targetFolder.startsWith("Download", ignoreCase = true) -> targetFolder
            targetFolder.startsWith("Movies", ignoreCase = true) -> targetFolder
            isMovies -> "Movies/KodikDown"
            else -> "Download/KodikDown"
        }

        val dir = File(targetFolder)
        if (!dir.exists()) {
            dir.mkdirs()
        }
        val storageDir = File(Environment.getExternalStorageDirectory(), relativeSubDir)
        if (!storageDir.exists()) {
            storageDir.mkdirs()
        }

        // 1. Try DocumentsContract folder URI with mime "vnd.android.document/directory"
        val possibleDocIds = listOf(
            "primary:$relativeSubDir",
            if (isMovies) "primary:Movies" else "primary:Download",
            "primary:"
        )

        for (docId in possibleDocIds) {
            try {
                val encoded = Uri.encode(docId)
                val contentUri = Uri.parse("content://com.android.externalstorage.documents/document/$encoded")
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(contentUri, "vnd.android.document/directory")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(intent)
                return
            } catch (_: Exception) {}
        }

        // 2. Try ACTION_VIEW_DOWNLOADS (standard system Downloads view)
        try {
            val intent = Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            return
        } catch (_: Exception) {}

        // 3. Fallback: FileProvider
        try {
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", dir)
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "vnd.android.document/directory")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            return
        } catch (_: Exception) {}

        Toast.makeText(context, "${context.getString(R.string.download_dir)}: $targetFolder", Toast.LENGTH_LONG).show()
    }

    fun openFile(context: Context, savedPathOrUri: String) {
        try {
            val intent = Intent(Intent.ACTION_VIEW).apply {
                if (savedPathOrUri.startsWith("content://")) {
                    setDataAndType(Uri.parse(savedPathOrUri), "video/mp4")
                } else {
                    val file = File(savedPathOrUri)
                    if (file.exists()) {
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
                        setDataAndType(uri, "video/mp4")
                    } else {
                        // Might be a public path stored via MediaStore; query MediaStore or Downloads
                        val uri = MediaStore.Video.Media.EXTERNAL_CONTENT_URI
                        setDataAndType(uri, "video/mp4")
                    }
                }
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(Intent.createChooser(intent, context.getString(R.string.open_file)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
        } catch (e: Exception) {
            Toast.makeText(context, "Could not open video: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    fun shareFile(context: Context, savedPathOrUri: String) {
        try {
            val uri = if (savedPathOrUri.startsWith("content://")) {
                Uri.parse(savedPathOrUri)
            } else {
                val file = File(savedPathOrUri)
                FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
            }
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "video/mp4"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(Intent.createChooser(intent, context.getString(R.string.share_file)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
        } catch (e: Exception) {
            Toast.makeText(context, "Could not share video: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    fun formatFileSize(bytes: Long): String {
        if (bytes <= 0) return "0 Б"
        val units = arrayOf("Б", "КБ", "МБ", "ГБ", "ТБ")
        val digitGroups = (Math.log10(bytes.toDouble()) / Math.log10(1024.0)).toInt().coerceIn(0, units.size - 1)
        val value = bytes / Math.pow(1024.0, digitGroups.toDouble())
        return String.format(java.util.Locale.US, "%.1f %s", value, units[digitGroups])
    }

    fun deleteFile(context: Context, pathOrUri: String): Boolean {
        return try {
            if (pathOrUri.startsWith("content://")) {
                val uri = Uri.parse(pathOrUri)
                val rows = context.contentResolver.delete(uri, null, null)
                rows > 0
            } else {
                val file = File(pathOrUri)
                if (file.exists()) file.delete() else false
            }
        } catch (_: Exception) {
            false
        }
    }
}
