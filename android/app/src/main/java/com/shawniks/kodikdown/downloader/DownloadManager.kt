package com.shawniks.kodikdown.downloader

import android.content.Context
import android.util.Log
import com.shawniks.kodikdown.data.DownloadItem
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.LibraryManager
import com.shawniks.kodikdown.util.FileUtils
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import java.io.File
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

object DownloadManager {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val downloader = HlsDownloader()

    private val _items = MutableStateFlow<List<DownloadItem>>(emptyList())
    val items: StateFlow<List<DownloadItem>> = _items.asStateFlow()

    private val activeJobs = ConcurrentHashMap<String, Job>()
    private val cancelledItems = ConcurrentHashMap<String, Boolean>()

    var maxConcurrentDownloads = 3
        set(value) {
            field = value.coerceIn(1, 5)
            semaphore = Semaphore(field)
        }
    private var semaphore = Semaphore(maxConcurrentDownloads)

    fun isAlreadyActive(url: String, fileName: String): Boolean {
        val targetName = fileName.removeSuffix(".mp4").trim()
        return _items.value.any { item ->
            !item.isTerminal && (
                item.url == url || 
                item.fileName.removeSuffix(".mp4").trim().equals(targetName, ignoreCase = true)
            )
        }
    }

    fun enqueueDownload(
        context: Context,
        title: String,
        fileName: String,
        url: String,
        quality: Int,
        isMp4: Boolean,
        downloadDir: String,
        translationTitle: String? = null
    ): String {
        if (isAlreadyActive(url, fileName)) {
            return ""
        }

        val id = UUID.randomUUID().toString()
        val item = DownloadItem(
            id = id,
            title = title,
            fileName = fileName,
            url = url,
            quality = quality,
            isMp4 = isMp4,
            status = DownloadStatus.QUEUED
        )

        val currentList = _items.value.toMutableList()
        currentList.add(0, item)
        _items.value = currentList

        // Record to persistent history
        HistoryManager.recordFromDownload(context, item, translationTitle)

        // Start background service
        DownloadService.start(context)

        // Launch worker coroutine
        val job = scope.launch {
            semaphore.withPermit {
                executeDownload(context, item, downloadDir)
            }
        }
        activeJobs[id] = job

        return id
    }

    private suspend fun executeDownload(context: Context, item: DownloadItem, downloadDir: String) {
        if (cancelledItems[item.id] == true) {
            updateItem(item.id) {
                it.status = DownloadStatus.CANCELLED
            }
            return
        }

        updateItem(item.id) {
            it.status = DownloadStatus.DOWNLOADING
            it.progress = 0f
        }

        val cacheDownloadDir = File(context.cacheDir, "downloads").apply { mkdirs() }
        val tempFile = File(cacheDownloadDir, "${item.id}.mp4")
        if (tempFile.exists()) tempFile.delete()

        try {
            if (item.isMp4) {
                var directSuccess = false
                try {
                    downloader.downloadDirectMp4(
                        url = item.url,
                        targetFile = tempFile,
                        isCancelled = { cancelledItems[item.id] == true }
                    ) { downloaded, total, speed, eta ->
                        updateItem(item.id) {
                            it.downloadedBytes = downloaded
                            it.totalBytes = total
                            it.speedBytesPerSec = speed
                            it.etaSeconds = eta
                            if (total != null && total > 0) {
                                it.progress = (downloaded.toFloat() / total.toFloat()).coerceIn(0f, 1f)
                            }
                        }
                    }
                    directSuccess = true
                } catch (e: Exception) {
                    if (cancelledItems[item.id] == true) throw e
                    Log.w("DownloadManager", "Direct MP4 download failed (${e.message}), falling back to HLS")
                }

                if (!directSuccess) {
                    val hlsUrl = if (item.url.contains(":hls:manifest.m3u8")) item.url else "${item.url}:hls:manifest.m3u8"
                    downloader.downloadHls(
                        manifestUrl = hlsUrl,
                        targetFile = tempFile,
                        isCancelled = { cancelledItems[item.id] == true }
                    ) { downloaded, total, speed, eta ->
                        updateItem(item.id) {
                            it.downloadedBytes = downloaded
                            it.totalBytes = total
                            it.speedBytesPerSec = speed
                            it.etaSeconds = eta
                            if (total != null && total > 0) {
                                it.progress = (downloaded.toFloat() / total.toFloat()).coerceIn(0f, 1f)
                            }
                        }
                    }
                }
            } else {
                downloader.downloadHls(
                    manifestUrl = item.url,
                    targetFile = tempFile,
                    isCancelled = { cancelledItems[item.id] == true }
                ) { downloaded, total, speed, eta ->
                    updateItem(item.id) {
                        it.downloadedBytes = downloaded
                        it.totalBytes = total
                        it.speedBytesPerSec = speed
                        it.etaSeconds = eta
                        if (total != null && total > 0) {
                            it.progress = (downloaded.toFloat() / total.toFloat()).coerceIn(0f, 1f)
                        }
                    }
                }
            }

            // Successfully downloaded into cache, now publish to public storage
            updateItem(item.id) {
                it.status = DownloadStatus.ASSEMBLING
            }

            val (publicPath, publicUri) = FileUtils.saveToPublicStorage(
                context = context,
                sourceTempFile = tempFile,
                baseFileName = item.fileName,
                targetFolder = downloadDir
            )

            try {
                tempFile.delete()
            } catch (_: Exception) {}

            updateItem(item.id) {
                it.status = DownloadStatus.FINISHED
                it.progress = 1f
                it.savedPath = publicPath
                it.contentUri = publicUri.toString()
            }

            // Update persistent history and refresh library
            HistoryManager.updateStatus(
                context = context,
                id = item.id,
                status = DownloadStatus.FINISHED,
                savedPath = publicPath,
                contentUri = publicUri.toString(),
                fileSize = item.downloadedBytes.takeIf { it > 0 } ?: item.totalBytes
            )
            LibraryManager.refresh(context, downloadDir)
        } catch (e: InterruptedException) {
            try { tempFile.delete() } catch (_: Exception) {}
            updateItem(item.id) {
                it.status = DownloadStatus.CANCELLED
            }
            HistoryManager.updateStatus(context, item.id, DownloadStatus.CANCELLED)
        } catch (e: Exception) {
            try { tempFile.delete() } catch (_: Exception) {}
            val isCancelled = cancelledItems[item.id] == true
            updateItem(item.id) {
                if (isCancelled) {
                    it.status = DownloadStatus.CANCELLED
                } else {
                    it.status = DownloadStatus.FAILED
                    it.errorMessage = e.message ?: "Unknown error"
                }
            }
            HistoryManager.updateStatus(
                context = context,
                id = item.id,
                status = if (isCancelled) DownloadStatus.CANCELLED else DownloadStatus.FAILED,
                error = e.message
            )
        } finally {
            activeJobs.remove(item.id)
            cancelledItems.remove(item.id)
            checkAllDone(context)
        }
    }

    fun cancelDownload(id: String) {
        cancelledItems[id] = true
        activeJobs[id]?.cancel()
        updateItem(id) {
            it.status = DownloadStatus.CANCELLED
        }
    }

    fun removeDownload(id: String) {
        cancelDownload(id)
        val currentList = _items.value.toMutableList()
        currentList.removeAll { it.id == id }
        _items.value = currentList
    }

    fun clearFinished() {
        val currentList = _items.value.toMutableList()
        currentList.removeAll { it.isTerminal }
        _items.value = currentList
    }

    private fun checkAllDone(context: Context) {
        val anyActive = _items.value.any { !it.isTerminal }
        if (!anyActive) {
            DownloadService.stop(context)
        }
    }

    private fun updateItem(id: String, action: (DownloadItem) -> Unit) {
        val currentList = _items.value.toMutableList()
        val index = currentList.indexOfFirst { it.id == id }
        if (index != -1) {
            val updated = currentList[index].copy()
            action(updated)
            currentList[index] = updated
            _items.value = currentList
        }
    }
}
