package com.shawniks.kodikdown.util

import android.app.DownloadManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.widget.Toast
import androidx.core.content.FileProvider
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.MediaFiles
import java.io.File
import java.io.FileNotFoundException
import java.io.IOException
import java.io.OutputStream
import java.util.Locale
import java.util.regex.Pattern
import kotlinx.coroutines.CancellationException

object FileUtils {
    /** Active transfers own this directory, even while a new job is being queued. */
    fun clearCache(cacheDir: File, codeCacheDir: File) {
        cacheDir.listFiles()?.filter { it.name != "downloads" }?.forEach { it.deleteRecursively() }
        codeCacheDir.listFiles()?.forEach { it.deleteRecursively() }
    }

    private val ILLEGAL_CHARS = Pattern.compile("""[<>:"/\\|?*\x00-\x1f]""")
    private val MEDIA_SUFFIX_RE =
        Pattern.compile("""\.(mp4|mkv|webm|avi|mov|m4v|flv|wmv|ts)$""", Pattern.CASE_INSENSITIVE)
    private val TEMPLATE_CHARS = Pattern.compile("%")
    private val RESERVED_NAMES =
        setOf(
            "con",
            "prn",
            "aux",
            "nul",
            "com1",
            "com2",
            "com3",
            "com4",
            "com5",
            "com6",
            "com7",
            "com8",
            "com9",
            "lpt1",
            "lpt2",
            "lpt3",
            "lpt4",
            "lpt5",
            "lpt6",
            "lpt7",
            "lpt8",
            "lpt9",
            "com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³",
        )

    fun safeFileName(raw: String, fallback: String = "video"): String {
        var cleaned = ILLEGAL_CHARS.matcher(raw).replaceAll("_").trim(' ', '.')
        cleaned = TEMPLATE_CHARS.matcher(cleaned).replaceAll("_")
        cleaned = cleaned.replace(Regex("\\s+"), " ")
        var end = 0
        var bytes = 0
        while (end < cleaned.length) {
            val codePoint = cleaned.codePointAt(end)
            val width = Character.charCount(codePoint)
            val encodedWidth = when {
                codePoint <= 0x7f -> 1
                codePoint <= 0x7ff -> 2
                width == 1 -> 3
                else -> 4
            }
            if (end + width > 120 || bytes + encodedWidth > 200) break
            bytes += encodedWidth
            end += width
        }
        cleaned = cleaned.substring(0, end)
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
     * Saves a completed video into public user storage using MediaStore (Android 10+) or standard
     * filesystem (Android 9 and below), bypassing Scoped Storage write restrictions.
     */
    fun publicDirectory(targetFolder: String): String {
        val external = runCatching { Environment.getExternalStorageDirectory().absolutePath.trimEnd('/') }.getOrDefault("")
        var relative = targetFolder.trim('/')
        if (external.isNotEmpty() && relative.startsWith(external.trim('/'))) {
            relative = relative.removePrefix(external.trim('/')).trim('/')
        }
        relative = relative
            .removePrefix("storage/emulated/0/")
            .removePrefix("storage/emulated/0")
            .removePrefix("sdcard/")
            .removePrefix("sdcard")
            .removePrefix("storage/self/primary/")
            .removePrefix("storage/self/primary")
            .trim('/')
        val root = relative.substringBefore('/')
        if (
            root !in setOf("Download", "Movies", "DCIM") ||
                relative.split('/').any { it == "." || it == ".." }
        ) {
            throw IOException("Choose this folder using the folder picker in Settings")
        }
        return relative
    }

    fun saveToPublicStorage(
        context: Context,
        sourceTempFile: File,
        baseFileName: String,
        targetFolder: String,
        series: String? = null,
        isCancelled: () -> Boolean = { false },
    ): Pair<String, Uri> {
        val fileName = "${safeFileName(baseFileName)}.mp4"
        fun copyTo(out: OutputStream) {
            sourceTempFile.inputStream().use { input ->
                val buffer = ByteArray(128 * 1024)
                while (true) {
                    if (isCancelled()) throw CancellationException("Download cancelled")
                    val count = input.read(buffer)
                    if (count < 0) break
                    out.write(buffer, 0, count)
                }
            }
            if (isCancelled()) throw CancellationException("Download cancelled")
        }
        if (isCancelled()) throw CancellationException("Download cancelled")
        if (targetFolder.startsWith("content://")) {
            val tree = Uri.parse(targetFolder)
            val root =
                DocumentsContract.buildDocumentUriUsingTree(
                    tree,
                    DocumentsContract.getTreeDocumentId(tree),
                )
            val parent = series?.let { seriesFolder(context, tree, root, safeFileName(it)) } ?: root
            val document =
                DocumentsContract.createDocument(
                    context.contentResolver,
                    parent,
                    "video/mp4",
                    fileName,
                ) ?: throw IOException("Could not create video in the selected folder")
            MediaFiles.setPending(document.toString(), true)
            try {
                (context.contentResolver.openOutputStream(document)
                        ?: throw IOException("Could not open the selected folder"))
                    .use { copyTo(it) }
                return Pair(document.toString(), document)
            } catch (e: Exception) {
                runCatching { DocumentsContract.deleteDocument(context.contentResolver, document) }
                throw e
            } finally { MediaFiles.setPending(document.toString(), false) }
        }
        val relativeSubDir = publicDirectory(targetFolder) + (series?.let { "/${safeFileName(it)}" } ?: "")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values =
                ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                    put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, "${relativeSubDir.trimEnd('/')}/")
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
            val collection =
                if (relativeSubDir.substringBefore('/') == "Download") {
                    MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                } else MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            val uri =
                context.contentResolver.insert(collection, values)
                    ?: throw IOException("Could not create video in public storage")
            try {
                (context.contentResolver.openOutputStream(uri)
                        ?: throw IOException("Could not open video output"))
                    .use { copyTo(it) }
                values.clear()
                values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                if (context.contentResolver.update(uri, values, null, null) != 1) {
                    throw IOException("Could not publish downloaded video")
                }
                // MediaStore may choose a different name to avoid overwriting an existing video.
                val actualName =
                    context.contentResolver
                        .query(uri, arrayOf(MediaStore.MediaColumns.DISPLAY_NAME), null, null, null)
                        ?.use { if (it.moveToFirst()) it.getString(0) else fileName } ?: fileName
                return Pair("/storage/emulated/0/$relativeSubDir/$actualName", uri)
            } catch (e: Exception) {
                runCatching { context.contentResolver.delete(uri, null, null) }
                throw e
            }
        }
        val directory = File(Environment.getExternalStorageDirectory(), relativeSubDir)
        if (!directory.mkdirs() && !directory.isDirectory)
            throw IOException("Could not create download folder")
        var target = File(directory, fileName)
        var index = 2
        while (!target.createNewFile()) {
            target = File(directory, "${safeFileName(baseFileName)} (${index++}).mp4")
        }
        MediaFiles.setPending(target.absolutePath, true)
        try {
            target.outputStream().use { copyTo(it) }
            scanMedia(context, target)
            return Pair(
                target.absolutePath,
                FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", target),
            )
        } catch (e: Exception) {
            target.delete()
            throw e
        } finally { MediaFiles.setPending(target.absolutePath, false) }
    }

    fun scanMedia(context: Context, file: File) {
        try {
            MediaScannerConnection.scanFile(
                context.applicationContext,
                arrayOf(file.absolutePath),
                arrayOf("video/mp4"),
                null,
            )
        } catch (_: Exception) {}
    }

    /** Opens a folder in the user's preferred file manager. */
    fun openFolder(context: Context, targetFolder: String) {
        if (targetFolder.startsWith("content://")) {
            try {
                val tree = Uri.parse(targetFolder)
                val document =
                    DocumentsContract.buildDocumentUriUsingTree(
                        tree,
                        DocumentsContract.getTreeDocumentId(tree),
                    )
                context.startActivity(
                    Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(document, DocumentsContract.Document.MIME_TYPE_DIR)
                        addFlags(
                            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK
                        )
                    }
                )
            } catch (e: Exception) {
                Toast.makeText(
                        context,
                        context.getString(R.string.open_folder) + ": " + e.message,
                        Toast.LENGTH_LONG,
                    )
                    .show()
            }
            return
        }
        val isMovies = targetFolder.contains("Movie", ignoreCase = true)
        val relativeSubDir =
            when {
                targetFolder.contains("/storage/emulated/0/") -> {
                    val sub = targetFolder.substringAfter("/storage/emulated/0/").trim('/')
                    if (sub.isNotEmpty()) sub
                    else if (isMovies) "Movies/KodikDown" else "Download/KodikDown"
                }
                targetFolder.startsWith("Download", ignoreCase = true) -> targetFolder
                targetFolder.startsWith("Movies", ignoreCase = true) -> targetFolder
                isMovies -> "Movies/KodikDown"
                else -> "Download/KodikDown"
            }

        val storageDir = File(Environment.getExternalStorageDirectory(), relativeSubDir)
        val canOpenFolder = storageDir.mkdirs() || storageDir.isDirectory

        // 1. Try DocumentsContract folder URI with mime "vnd.android.document/directory"
        val possibleDocIds =
            listOfNotNull(
                "primary:$relativeSubDir".takeIf { canOpenFolder || Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q },
                if (isMovies) "primary:Movies" else "primary:Download",
                "primary:",
            )

        for (docId in possibleDocIds) {
            try {
                val encoded = Uri.encode(docId)
                val contentUri =
                    Uri.parse("content://com.android.externalstorage.documents/document/$encoded")
                val intent =
                    Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(contentUri, "vnd.android.document/directory")
                        addFlags(
                            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK
                        )
                    }
                context.startActivity(intent)
                return
            } catch (_: Exception) {}
        }

        // 2. Try ACTION_VIEW_DOWNLOADS (standard system Downloads view)
        try {
            val intent =
                Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            context.startActivity(intent)
            return
        } catch (_: Exception) {}

        // 3. Fallback: FileProvider
        try {
            val uri =
                FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", storageDir)
            val intent =
                Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "vnd.android.document/directory")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            context.startActivity(intent)
            return
        } catch (_: Exception) {}

        Toast.makeText(
                context,
                "${context.getString(R.string.download_dir)}: $targetFolder",
                Toast.LENGTH_LONG,
            )
            .show()
    }

    @Synchronized
    private fun seriesFolder(context: Context, tree: Uri, parent: Uri, name: String): Uri {
        val resolver = context.contentResolver
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getDocumentId(parent))
        val fields = arrayOf(
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
        )
        resolver.query(children, fields, null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == name && cursor.getString(2) == DocumentsContract.Document.MIME_TYPE_DIR) {
                    return DocumentsContract.buildDocumentUriUsingTree(tree, cursor.getString(0))
                }
            }
        }
        return DocumentsContract.createDocument(resolver, parent, DocumentsContract.Document.MIME_TYPE_DIR, name)
            ?: throw IOException("Could not create series folder")
    }

    fun openFile(context: Context, savedPathOrUri: String) {
        MediaFiles.withAvailable(context, savedPathOrUri) {
            openFileUnchecked(context, savedPathOrUri)
        }
    }

    private fun openFileUnchecked(context: Context, savedPathOrUri: String) {
        try {
            val intent =
                Intent(Intent.ACTION_VIEW).apply {
                    if (savedPathOrUri.startsWith("content://")) {
                        setDataAndType(Uri.parse(savedPathOrUri), "video/mp4")
                    } else {
                        val file = File(savedPathOrUri)
                        if (file.exists()) {
                            val uri =
                                FileProvider.getUriForFile(
                                    context,
                                    "${context.packageName}.fileprovider",
                                    file,
                                )
                            setDataAndType(uri, "video/mp4")
                        } else {
                            // Might be a public path stored via MediaStore; query MediaStore or
                            // Downloads
                            throw FileNotFoundException("Video file no longer exists")
                        }
                    }
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            context.startActivity(
                Intent.createChooser(intent, context.getString(R.string.open_file)).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            )
        } catch (e: Exception) {
            Toast.makeText(context, "Could not open video: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    fun shareFile(context: Context, savedPathOrUri: String) {
        MediaFiles.withAvailable(context, savedPathOrUri) {
            shareFileUnchecked(context, savedPathOrUri)
        }
    }

    private fun shareFileUnchecked(context: Context, savedPathOrUri: String) {
        try {
            val uri =
                if (savedPathOrUri.startsWith("content://")) {
                    Uri.parse(savedPathOrUri)
                } else {
                    val file = File(savedPathOrUri)
                    FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
                }
            val intent =
                Intent(Intent.ACTION_SEND).apply {
                    type = "video/mp4"
                    putExtra(Intent.EXTRA_STREAM, uri)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            context.startActivity(
                Intent.createChooser(intent, context.getString(R.string.share_file)).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            )
        } catch (e: Exception) {
            Toast.makeText(context, "Could not share video: ${e.message}", Toast.LENGTH_SHORT)
                .show()
        }
    }

    fun formatFileSize(bytes: Long): String {
        if (bytes <= 0) return "0 Б"
        val units = arrayOf("Б", "КБ", "МБ", "ГБ", "ТБ")
        val digitGroups =
            (Math.log10(bytes.toDouble()) / Math.log10(1024.0)).toInt().coerceIn(0, units.size - 1)
        val value = bytes / Math.pow(1024.0, digitGroups.toDouble())
        return String.format(Locale.US, "%.1f %s", value, units[digitGroups])
    }

    fun deleteFile(context: Context, pathOrUri: String): Boolean {
        if (MediaFiles.isPending(pathOrUri)) return false
        return try {
            if (pathOrUri.startsWith("content://")) {
                val uri = Uri.parse(pathOrUri)
                if (DocumentsContract.isDocumentUri(context, uri)) {
                    DocumentsContract.deleteDocument(context.contentResolver, uri)
                } else context.contentResolver.delete(uri, null, null) > 0
            } else {
                val file = File(pathOrUri)
                if (file.exists()) file.delete() else false
            }
        } catch (_: Exception) {
            false
        }
    }
}
