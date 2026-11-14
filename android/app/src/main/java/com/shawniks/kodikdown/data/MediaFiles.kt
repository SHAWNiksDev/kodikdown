package com.shawniks.kodikdown.data

import android.content.Context
import android.net.Uri
import com.shawniks.kodikdown.KodikApp
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.downloader.DownloadManager
import java.io.File
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Cache only metadata availability. Never read a video or query storage from a row binding. */
object MediaFiles {
    private val pending = java.util.concurrent.ConcurrentHashMap.newKeySet<String>()
    fun isPending(reference: String?): Boolean = reference != null && reference in pending
    fun setPending(reference: String, value: Boolean) {
        if (value) pending.add(reference) else { pending.remove(reference); requestRefresh() }
    }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val requests = Channel<Unit>(Channel.CONFLATED)
    private val lock = Mutex()
    private val state = MutableStateFlow<Map<String, Boolean>>(emptyMap())
    private val missingCheckedAt = mutableMapOf<String, Long>() // protected by lock
    val availability = state.asStateFlow()
    private fun key(path: String?, uri: String?) = "${path.orEmpty()}|${uri.orEmpty()}"

    init {
        scope.launch {
            for (request in requests) {
                delay(250)
                refresh(KodikApp.instance)
            }
        }
    }

    fun requestRefresh() { requests.trySend(Unit) }
    fun isAvailable(path: String?, uri: String?): Boolean = !isPending(path) && !isPending(uri) && state.value[key(path, uri)] == true

    fun exists(context: Context, path: String?, uri: String?): Boolean {
        if (isPending(path) || isPending(uri)) return false
        // App-owned public files are often directly readable. A stat avoids opening
        // a Binder-backed descriptor for every history row on every refresh.
        if (!path.isNullOrBlank() && !path.startsWith("content://")) {
            val file = File(path)
            if (file.isFile && file.canRead() && file.length() > 0) return true
        }
        if (!uri.isNullOrBlank()) {
            try {
                context.contentResolver.openAssetFileDescriptor(Uri.parse(uri), "r")?.use { return true }
            } catch (_: Exception) { /* A stale MediaStore row is not a readable video. */ }
        }
        return false
    }

    suspend fun refresh(context: Context, force: Boolean = true) = withContext(Dispatchers.IO) {
        lock.withLock {
            val references = HistoryManager.items.value.map { it.savedPath to it.contentUri } +
                DownloadManager.items.value.filter { it.isFinished }.map { it.savedPath to it.contentUri } +
                LibraryManager.items.value.map { it.filePath to it.contentUri }
            val now = android.os.SystemClock.elapsedRealtime()
            val checked = references.filter { !it.first.isNullOrBlank() || !it.second.isNullOrBlank() }.distinct().associate { (path, uri) ->
                val reference = key(path, uri)
                val missing = missingCheckedAt[reference]
                val available = if (!force && missing != null && now - missing < 30_000L) false
                    else exists(context, path, uri)
                if (available) missingCheckedAt.remove(reference)
                else if (force || missing == null || now - missing >= 30_000L) missingCheckedAt[reference] = now
                reference to available
            }
            missingCheckedAt.keys.retainAll(checked.keys)
            state.value = checked
            LibraryManager.pruneUnavailable { path, uri -> isAvailable(path, uri) }
        }
    }

    fun withAvailable(context: Context, pathOrUri: String, action: () -> Unit) {
        scope.launch {
            val available = if (pathOrUri.startsWith("content://")) exists(context, null, pathOrUri)
                else exists(context, pathOrUri, null)
            withContext(Dispatchers.Main) {
                if (available) action()
                else android.widget.Toast.makeText(context, R.string.file_missing, android.widget.Toast.LENGTH_SHORT).show()
            }
            if (!available) requestRefresh()
        }
    }
}
