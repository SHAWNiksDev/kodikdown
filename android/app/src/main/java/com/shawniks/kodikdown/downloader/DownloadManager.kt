package com.shawniks.kodikdown.downloader

import android.content.Context
import android.util.Log
import com.shawniks.kodikdown.KodikApp
import com.shawniks.kodikdown.data.DownloadItem
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.HistoryItem
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.HistoryRetry
import com.shawniks.kodikdown.data.LibraryManager
import com.shawniks.kodikdown.data.ResolvedVideo
import com.shawniks.kodikdown.data.StreamVariant
import com.shawniks.kodikdown.kodik.CatalogClient
import com.shawniks.kodikdown.kodik.KodikClient
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.io.IOException
import java.util.UUID
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
    private val _items = MutableStateFlow<List<DownloadItem>>(emptyList())
    val items: StateFlow<List<DownloadItem>> = _items.asStateFlow()
    private val activeJobs = mutableMapOf<String, Job>()
    private val pending = mutableMapOf<String, PendingDownload>()
    private val prepareFirst = mutableMapOf<String, suspend () -> ResolvedVideo>()
    private val attempted = mutableSetOf<String>()
    private val stops = mutableMapOf<String, DownloadStatus>()
    private var storage: PendingDownloads? = null
    @Volatile var maxConcurrentDownloads = 3
        set(value) { field = value.coerceIn(1, 5) }

    @Synchronized
    fun restore(context: Context) {
        if (storage != null) return
        val store = PendingDownloads(context)
        val completed = LibraryManager.recordedIds(context)
        for (download in store.load()) {
            if (download.item.id in completed) continue
            pending[download.item.id] = download
            attempted.add(download.item.id)
        }
        _items.value = pending.values.map { it.item }
        storage = store
        val abandoned = File(context.filesDir, "downloads").listFiles().orEmpty()
            .filter { it.name !in pending }
        if (abandoned.isNotEmpty()) scope.launch { abandoned.forEach { it.deleteRecursively() } }
    }

    @Synchronized
    fun resumePending(context: Context) {
        if (_items.value.none { it.status == DownloadStatus.QUEUED }) return
        try {
            DownloadService.start(context.applicationContext)
            schedule(context.applicationContext)
        } catch (error: IllegalStateException) {
            Log.w("DownloadManager", "Downloads will resume when the app is open", error)
        }
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
        restore(app)
        val name = FileUtils.safeFileName(fileName)
        if (isAlreadyActive(url, name, series)) return ""
        val item = DownloadItem(UUID.randomUUID().toString(), title, name, url, quality, isMp4,
            sourceInput = sourceInput, retryInput = retryInput, series = series)
        pending[item.id] = PendingDownload(item, downloadDir, translationTitle, hlsUrl, fallbackVariants, referer)
        if (prepare != null) prepareFirst[item.id] = prepare
        _items.update { it + item }
        HistoryManager.recordFromDownload(app, item, translationTitle)
        saveQueue()
        resumePending(app)
        return item.id
    }

    private fun schedule(context: Context) {
        val freeSlots = maxConcurrentDownloads - activeJobs.size
        if (freeSlots <= 0) return
        val next = _items.value.filter { it.status == DownloadStatus.QUEUED && it.id !in activeJobs }
        for (row in next.take(freeSlots)) {
            val request = pending[row.id] ?: continue
            val prepare = prepareFirst.remove(row.id)
            val retry = !attempted.add(row.id)
            val job = scope.launch(start = CoroutineStart.LAZY) {
                try {
                    val resolved = prepare?.invoke()
                    val transfer = when {
                        resolved != null -> pickTransfer(request, resolved.pick(row.quality), resolved.variants)
                        retry -> refreshTransfer(request)
                        else -> request
                    }
                    executeDownload(context, transfer.item, transfer.directory, transfer.hls,
                        transfer.variants, transfer.referer)
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    currentCoroutineContext().ensureActive()
                    updateItem(row.id) {
                        it.copy(status = DownloadStatus.FAILED, errorMessage = error.message ?: "Download failed")
                    }
                }
            }
            activeJobs[row.id] = job
            job.invokeOnCompletion { complete(context, row.id, it) }
            updateItem(row.id) { it.copy(status = DownloadStatus.DOWNLOADING) }
            job.start()
        }
    }

    private suspend fun refreshTransfer(request: PendingDownload): PendingDownload {
        val item = request.item
        val kodik = KodikClient()
        val catalogs = CatalogClient(kodik)
        val history = HistoryItem(item.id, item.title, item.fileName, item.url, item.quality,
            translation = request.translation, isMp4 = item.isMp4, sourceInput = item.sourceInput,
            retryInput = item.retryInput, series = item.series)
        if (item.retryInput == null && item.sourceInput == null) return request
        val selection = HistoryRetry.resolve(history) { url, track ->
            if (track == null) catalogs.resolve(url) else kodik.resolve(url, track)
        }
        return pickTransfer(request, selection.variant, selection.variants)
    }

    private fun pickTransfer(request: PendingDownload, variant: StreamVariant, variants: List<StreamVariant>): PendingDownload {
        val direct = variant.directMp4.takeIf { request.item.isMp4 }
        return request.copy(
            item = request.item.copy(url = direct ?: variant.url,
                quality = variant.quality.takeIf { it > 0 } ?: request.item.quality,
                isMp4 = variant.kind == "mp4" || direct != null),
            hls = variant.url,
            variants = variants,
            referer = variant.referer,
        )
    }

    @Synchronized
    private fun complete(context: Context, id: String, cause: Throwable?) {
        activeJobs.remove(id)
        val stop = stops.remove(id)
        if (cause is CancellationException) {
            updateItem(id) {
                if (it.isTerminal) it else it.copy(status = stop ?: DownloadStatus.PAUSED, waitingForNetwork = false)
            }
        }
        val item = _items.value.firstOrNull { it.id == id }
        if (item?.status == DownloadStatus.CANCELLED || item?.status == DownloadStatus.FINISHED) {
            pending.remove(id)
            attempted.remove(id)
            workDirectory(context, id).deleteRecursively()
        }
        saveQueue()
        schedule(context)
    }

    private fun workDirectory(context: Context, id: String) = File(context.filesDir, "downloads/$id")

    private fun saveQueue() {
        val entries = _items.value.mapNotNull { row ->
            val status = stops[row.id] ?: row.status
            if (status == DownloadStatus.CANCELLED || status == DownloadStatus.FINISHED) return@mapNotNull null
            pending[row.id]?.let { request ->
                request.copy(item = request.item.copy(status = status,
                    errorMessage = row.errorMessage))
            }
        }
        if (storage?.save(entries) == false) {
            Log.e("DownloadManager", "Could not save the download queue")
        }
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
        val directory = workDirectory(context, item.id)
        if (!directory.mkdirs() && !directory.isDirectory)
            throw IOException("Could not create download cache")
        val tempFile = File(directory, "video.mp4")
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
                    { stopRequested(item.id) },
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
                    keepPartial = true,
                )
                try {
                    if (direct != null || source.kind == "mp4") {
                        try {
                            downloader.downloadDirectMp4(
                                direct ?: source.url,
                                tempFile,
                                { stopRequested(item.id) },
                                progress,
                                onNetworkWait = networkWait,
                                onProcessing = processing,
                                referer = source.referer,
                                keepPartial = true,
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
                    stopRequested(item.id)
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
            File("${tempFile.absolutePath}.mux.part").delete()
        }
    }

    @Synchronized
    private fun enterAssembly(id: String) {
        if (id in stops) throw CancellationException("Download cancelled")
        updateItem(id) {
            it.copy(status = DownloadStatus.ASSEMBLING, speedBytesPerSec = 0, etaSeconds = null)
        }
    }

    @Synchronized
    private fun stopRequested(id: String): Boolean = id in stops

    @Synchronized
    fun cancelDownload(id: String) = stop(id, DownloadStatus.CANCELLED)

    @Synchronized
    fun pauseDownload(id: String) = stop(id, DownloadStatus.PAUSED)

    private fun stop(id: String, status: DownloadStatus) {
        val item = _items.value.firstOrNull { it.id == id } ?: return
        if (item.isTerminal || item.status == DownloadStatus.ASSEMBLING || id in stops) return
        val job = activeJobs[id]
        if (job == null) {
            updateItem(id) { it.copy(status = status, waitingForNetwork = false) }
            if (status == DownloadStatus.CANCELLED) {
                pending.remove(id)
                attempted.remove(id)
                prepareFirst.remove(id)
                workDirectory(KodikApp.instance, id).deleteRecursively()
            }
            saveQueue()
        } else {
            stops[id] = status
            saveQueue()
            job.cancel()
        }
    }

    @Synchronized
    fun pauseAll() {
        // Withdraw queued work before a running download can free its slot.
        _items.value.filter { it.status == DownloadStatus.QUEUED }.forEach { pauseDownload(it.id) }
        _items.value.filter { it.status == DownloadStatus.DOWNLOADING }.forEach { pauseDownload(it.id) }
    }

    @Synchronized
    fun resume(context: Context, id: String) {
        requeue(id)
        saveQueue()
        resumePending(context)
    }

    @Synchronized
    fun resumeAll(context: Context, status: DownloadStatus) {
        _items.value.filter { it.status == status }.forEach { requeue(it.id) }
        saveQueue()
        resumePending(context)
    }

    private fun requeue(id: String) {
        if (id in pending && id !in activeJobs) updateItem(id) {
            if (it.status == DownloadStatus.PAUSED || it.status == DownloadStatus.FAILED)
                it.copy(status = DownloadStatus.QUEUED, errorMessage = null, waitingForNetwork = false)
            else it
        }
    }

    @Synchronized
    fun prioritize(id: String) {
        val item = _items.value.firstOrNull { it.id == id && it.status == DownloadStatus.QUEUED } ?: return
        _items.update { listOf(item) + it.filterNot { row -> row.id == id } }
        saveQueue()
    }

    @Synchronized
    fun removeDownload(id: String) {
        if (_items.value.none { it.id == id && it.isTerminal } || id in activeJobs) return
        _items.update { list -> list.filterNot { it.id == id } }
        if (pending.remove(id) != null) {
            attempted.remove(id)
            workDirectory(KodikApp.instance, id).deleteRecursively()
        }
        saveQueue()
    }

    @Synchronized
    fun clearFinished() {
        _items.value.filter { it.isTerminal }.forEach { removeDownload(it.id) }
    }

    @Synchronized
    private fun updateItem(id: String, transform: (DownloadItem) -> DownloadItem) {
        val previous = _items.value.firstOrNull { it.id == id } ?: return
        val updated = transform(previous)
        _items.update { list -> list.map { if (it.id == id) updated else it } }
        if (updated.status != previous.status) {
            HistoryManager.recordFromDownload(KodikApp.instance, updated, pending[id]?.translation)
        }
    }
}
