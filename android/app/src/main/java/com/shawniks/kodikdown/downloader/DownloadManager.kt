package com.shawniks.kodikdown.downloader

import android.content.Context
import com.shawniks.kodikdown.KodikApp
import com.shawniks.kodikdown.data.DownloadItem
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.LibraryManager
import com.shawniks.kodikdown.data.ResolvedVideo
import com.shawniks.kodikdown.data.StreamVariant
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.io.IOException
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

object DownloadManager {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val downloader = HlsDownloader()
    private val limiter = DownloadLimiter(3)
    private val _items = MutableStateFlow<List<DownloadItem>>(emptyList())
    val items: StateFlow<List<DownloadItem>> = _items.asStateFlow()
    private val activeJobs = ConcurrentHashMap<String, Job>()
    private val cancelledItems = ConcurrentHashMap.newKeySet<String>()

    var maxConcurrentDownloads = 3
        set(value) {
            field = value.coerceIn(1, 5)
            limiter.setLimit(field)
        }

    fun isActive(id: String): Boolean = _items.value.any { it.id == id && !it.isTerminal }

    fun isAssembling(id: String): Boolean =
        _items.value.any { it.id == id && it.status == DownloadStatus.ASSEMBLING }

    fun isAlreadyActive(url: String, fileName: String, series: String? = null): Boolean {
        val name = FileUtils.safeFileName(fileName)
        return _items.value.any {
            !it.isTerminal && (it.url == url || it.retryInput == url ||
                it.series == series && it.fileName.equals(name, ignoreCase = true))
        }
    }

    @Synchronized
    fun enqueueDownload(
        context: Context,
        title: String,
        fileName: String,
        url: String,
        quality: Int,
        isMp4: Boolean,
        downloadDir: String,
        translationTitle: String? = null,
        hlsUrl: String? = null,
        fallbackVariants: List<StreamVariant> = emptyList(),
        sourceInput: String? = null,
        retryInput: String? = null,
        series: String? = null,
        prepare: (suspend () -> ResolvedVideo)? = null,
        referer: String? = null,
    ): String {
        val app = context.applicationContext
        val name = FileUtils.safeFileName(fileName)
        if (isAlreadyActive(url, name, series)) return ""
        val item = DownloadItem(UUID.randomUUID().toString(), title, name, url, quality, isMp4,
            sourceInput = sourceInput, retryInput = retryInput, series = series)
        _items.update { listOf(item) + it }
        HistoryManager.recordFromDownload(app, item, translationTitle)
        try {
            DownloadService.start(app)
        } catch (e: Exception) {
            updateItem(item.id) {
                it.copy(status = DownloadStatus.FAILED, errorMessage = e.message)
            }
            return item.id
        }
        val job =
            scope.launch(start = CoroutineStart.LAZY) {
                try {
                    limiter.withSlot {
                        val resolved = prepare?.invoke()
                        if (resolved == null) {
                            executeDownload(app, item, downloadDir, hlsUrl, fallbackVariants, referer)
                        } else {
                            val variant = resolved.pick(quality)
                            val direct = variant.directMp4.takeIf { isMp4 }
                            executeDownload(app, item.copy(
                                url = direct ?: variant.url, quality = variant.quality.takeIf { it > 0 } ?: quality,
                                isMp4 = variant.kind == "mp4" || direct != null,
                            ), downloadDir, variant.url, resolved.variants, variant.referer)
                        }
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    currentCoroutineContext().ensureActive()
                    updateItem(item.id) {
                        it.copy(
                            status = DownloadStatus.FAILED,
                            errorMessage = e.message ?: "Download failed",
                        )
                    }
                }
            }
        activeJobs[item.id] = job
        job.invokeOnCompletion { cause ->
            if (cause is CancellationException) {
                updateItem(item.id) {
                    if (it.isTerminal) it else it.copy(status = DownloadStatus.CANCELLED)
                }
            }
            activeJobs.remove(item.id)
            cancelledItems.remove(item.id)
        }
        job.start()
        return item.id
    }

    private suspend fun executeDownload(
        context: Context,
        item: DownloadItem,
        downloadDir: String,
        hlsUrl: String?,
        fallbackVariants: List<StreamVariant>,
        referer: String? = null,
    ) {
        val networkWait: (Boolean) -> Unit = { waiting ->
            if (_items.value.firstOrNull { it.id == item.id }?.waitingForNetwork != waiting) {
                updateItem(item.id) { it.copy(waitingForNetwork = waiting,
                    speedBytesPerSec = if (waiting) 0 else it.speedBytesPerSec,
                    etaSeconds = if (waiting) null else it.etaSeconds) }
            }
        }
        val directory = File(context.cacheDir, "downloads")
        if (!directory.mkdirs() && !directory.isDirectory)
            throw IOException("Could not create download cache")
        val tempFile = File(directory, "${item.id}.mp4")
        val primaryKind = if (item.isMp4 && (hlsUrl == null || hlsUrl == item.url)) "mp4" else "hls"
        val primary =
            StreamVariant(
                item.quality,
                hlsUrl ?: item.url,
                primaryKind,
                if (item.isMp4) item.url else null,
                referer,
            )
        val sources =
            (listOf(primary) + fallbackVariants.filter { it.quality < item.quality }).distinctBy {
                it.url
            }
        try {
            for ((index, source) in sources.withIndex()) {
                currentCoroutineContext().ensureActive()
                val direct = if (item.isMp4) source.directMp4 else null
                updateItem(item.id) {
                    it.copy(
                        status = DownloadStatus.DOWNLOADING,
                        quality = source.quality,
                        url = direct ?: source.url,
                        isMp4 = direct != null || source.kind == "mp4",
                        progress = 0f,
                        downloadedFragments = 0,
                        fragmentCount = 0,
                        downloadedBytes = 0,
                        totalBytes = null,
                        speedBytesPerSec = 0,
                        etaSeconds = null,
                    )
                }
                val progress: (Long, Long?, Long, Long?) -> Unit = { bytes, total, speed, eta ->
                    updateItem(item.id) {
                        it.copy(
                            downloadedBytes = bytes,
                            totalBytes = total,
                            speedBytesPerSec = speed,
                            etaSeconds = eta,
                            progress =
                                if (total != null && total > 0)
                                    (bytes.toFloat() / total).coerceIn(0f, 1f)
                                else it.progress,
                        )
                    }
                }
                val processing = { enterAssembly(item.id) }
                suspend fun downloadHls() = downloader.downloadHls(
                    source.url,
                    tempFile,
                    { item.id in cancelledItems },
                    source.quality,
                    onProgress = progress,
                    onFragmentProgress = { done, count ->
                        updateItem(item.id) {
                            it.copy(downloadedFragments = done, fragmentCount = count,
                                progress = done.toFloat() / count)
                        }
                    },
                    onNetworkWait = networkWait,
                    onProcessing = processing,
                    referer = source.referer,
                )
                try {
                    if (direct != null || source.kind == "mp4") {
                        try {
                            downloader.downloadDirectMp4(
                                direct ?: source.url,
                                tempFile,
                                { item.id in cancelledItems },
                                progress,
                                onNetworkWait = networkWait,
                                onProcessing = processing,
                                referer = source.referer,
                            )
                        } catch (e: IOException) {
                            if (source.kind == "mp4" || source.url == direct) throw e
                            updateItem(item.id) {
                                it.copy(
                                    url = source.url,
                                    status = DownloadStatus.DOWNLOADING,
                                    isMp4 = false,
                                    downloadedBytes = 0,
                                    totalBytes = null,
                                    progress = 0f,
                                )
                            }
                            downloadHls()
                        }
                    } else {
                        downloadHls()
                    }
                    break
                } catch (e: IOException) {
                    tempFile.delete()
                    if (index == sources.lastIndex || e !is DownloadHttpException || e.code !in setOf(403, 404)) throw e
                }
            }
            currentCoroutineContext().ensureActive()
            enterAssembly(item.id)
            val (path, uri) =
                FileUtils.saveToPublicStorage(context, tempFile, item.fileName, downloadDir, item.series) {
                    item.id in cancelledItems
                }
            updateItem(item.id) {
                it.copy(
                    status = DownloadStatus.FINISHED,
                    progress = 1f,
                    savedPath = path,
                    contentUri = uri.toString(),
                )
            }
            val finished = _items.value.firstOrNull { it.id == item.id } ?: item
            LibraryManager.record(context, finished)
        } finally {
            tempFile.delete()
            File("${tempFile.absolutePath}.part").delete()
            File("${tempFile.absolutePath}.mux.part").delete()
        }
    }

    @Synchronized
    private fun enterAssembly(id: String) {
        if (id in cancelledItems) throw CancellationException("Download cancelled")
        updateItem(id) {
            it.copy(status = DownloadStatus.ASSEMBLING, speedBytesPerSec = 0, etaSeconds = null)
        }
    }

    @Synchronized
    fun cancelDownload(id: String) {
        if (_items.value.none { it.id == id && !it.isTerminal } || isAssembling(id)) return
        cancelledItems.add(id)
        activeJobs[id]?.cancel()
    }

    @Synchronized
    fun removeDownload(id: String) {
        _items.update { list -> list.filterNot { it.id == id && it.isTerminal } }
    }

    fun clearFinished() {
        _items.update { list -> list.filterNot { it.isTerminal } }
    }

    @Synchronized
    private fun updateItem(id: String, transform: (DownloadItem) -> DownloadItem) {
        val previous = _items.value.firstOrNull { it.id == id } ?: return
        val updated = transform(previous)
        _items.update { list -> list.map { if (it.id == id) updated else it } }
        if (updated.status != previous.status) {
            HistoryManager.recordFromDownload(KodikApp.instance, updated)
        }
    }
}
