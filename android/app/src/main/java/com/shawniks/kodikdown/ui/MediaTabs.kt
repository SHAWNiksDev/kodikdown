package com.shawniks.kodikdown.ui

import android.content.Intent
import android.net.Uri
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.SimpleItemAnimator
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.HistoryItem
import com.shawniks.kodikdown.data.HistoryLinks
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.LibraryItem
import com.shawniks.kodikdown.data.LibraryManager
import com.shawniks.kodikdown.data.MediaFiles
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.databinding.ActivityMainBinding
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

internal class MediaTabs(
    private val activity: AppCompatActivity,
    private val prefs: PreferencesManager,
    private val currentBinding: () -> ActivityMainBinding,
    private val triggerHaptic: (Int) -> Unit,
    private val onTransfersChanged: () -> Unit,
    private val requestHistoryRetry: (HistoryItem) -> Unit,
    private val copyLink: (String) -> Unit,
) {
    private val binding get() = currentBinding()
    private val uiCollectors = mutableListOf<Job>()
    private lateinit var downloadAdapter: DownloadAdapter
    private lateinit var libraryAdapter: LibraryAdapter
    private lateinit var historyAdapter: HistoryAdapter

    private enum class SelectionType { NONE, DOWNLOADS, LIBRARY, HISTORY }
    private var selectionType = SelectionType.NONE
    var isSelectionMode = false
        private set

    fun install() {
        initDownloadsList()
        initLibrary()
        initHistory()
        initSelectionBar()
    }

    fun unbind() {
        uiCollectors.forEach { it.cancel() }
        uiCollectors.clear()
        cancelDownloadDialog?.dismiss()
        isSelectionMode = false
        selectionType = SelectionType.NONE
    }

    private var cancelDownloadDialog: AlertDialog? = null
    private var cancelDownloadDialogId: String? = null

    private fun requestDownloadCancellation(id: String) {
        val item = DownloadManager.items.value.firstOrNull { it.id == id } ?: return
        if (item.isTerminal) {
            DownloadManager.removeDownload(id)
            return
        }
        if (DownloadManager.isAssembling(id)) return
        if (!prefs.confirmCancelDownload) {
            DownloadManager.cancelDownload(id)
            return
        }
        if (cancelDownloadDialog?.isShowing == true) return
        cancelDownloadDialogId = id
        cancelDownloadDialog = MaterialAlertDialogBuilder(activity)
            .setTitle(R.string.confirm_cancel_title)
            .setMessage(activity.getString(R.string.confirm_cancel_message, item.title))
            .setPositiveButton(R.string.stop_download) { _, _ -> DownloadManager.cancelDownload(id) }
            .setNegativeButton(R.string.keep_downloading, null)
            .setOnDismissListener {
                cancelDownloadDialog = null
                cancelDownloadDialogId = null
            }
            .show()
    }

    private fun initDownloadsList() {
        downloadAdapter =
            DownloadAdapter(
                onItemClick = {
                    triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
                    if (downloadAdapter.selectedIds.isEmpty()) exitSelectionMode()
                    else updateSelectionCount(downloadAdapter.selectedIds.size)
                },
                onItemLongClick = { item ->
                    if (!isSelectionMode && item.isTerminal) {
                        enterSelectionMode(SelectionType.DOWNLOADS, item.id)
                        true
                    } else false
                },
                onCancelClicked = { item ->
                    requestDownloadCancellation(item.id)
                },
                onOpenClicked = { item ->
                    val pathOrUri = item.contentUri ?: item.savedPath
                    if (!pathOrUri.isNullOrEmpty()) {
                        FileUtils.openFile(activity, pathOrUri)
                    }
                },
                onShareClicked = { item ->
                    val pathOrUri = item.contentUri ?: item.savedPath
                    if (!pathOrUri.isNullOrEmpty()) {
                        FileUtils.shareFile(activity, pathOrUri)
                    }
                },
            )

        binding.rvDownloads.apply {
            layoutManager = LinearLayoutManager(activity)
            adapter = downloadAdapter
            (itemAnimator as? SimpleItemAnimator)?.supportsChangeAnimations = false
        }

        ItemTouchHelper(SwipeToDeleteCallback(activity, canSwipe = { position ->
            prefs.swipeToDelete && !isSelectionMode &&
                downloadAdapter.currentList.getOrNull(position)?.isTerminal == true
        }) { position, _ ->
            val item = downloadAdapter.currentList.getOrNull(position) ?: return@SwipeToDeleteCallback
            val adapter = downloadAdapter
            val reset = { adapter.refreshRow(item.id) }
            if (!prefs.swipeToDelete || isSelectionMode || !item.isTerminal) {
                reset()
                return@SwipeToDeleteCallback
            }
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            if (prefs.confirmSwipeDelete) {
                MaterialAlertDialogBuilder(activity)
                    .setTitle(R.string.delete)
                    .setMessage(R.string.remove_download_confirm)
                    .setPositiveButton(R.string.delete) { _, _ -> DownloadManager.removeDownload(item.id) }
                    .setNegativeButton(R.string.cancel) { _, _ -> reset() }
                    .setOnCancelListener { reset() }
                    .show()
            } else DownloadManager.removeDownload(item.id)
        }).attachToRecyclerView(binding.rvDownloads)

        uiCollectors += activity.lifecycleScope.launch {
            DownloadManager.items.collect { items ->
                downloadAdapter.submitList(items)
                cancelDownloadDialogId?.let { id ->
                    if (!DownloadManager.isActive(id) || DownloadManager.isAssembling(id)) cancelDownloadDialog?.dismiss()
                }
                onTransfersChanged()
                if (items.isEmpty()) {
                    binding.tvDownloadsEmpty.visibility = View.VISIBLE
                    binding.rvDownloads.visibility = View.GONE
                } else {
                    binding.tvDownloadsEmpty.visibility = View.GONE
                    binding.rvDownloads.visibility = View.VISIBLE
                }
            }
        }
        uiCollectors += activity.lifecycleScope.launch {
            var previous = emptyMap<MediaFiles.Reference, Boolean>()
            MediaFiles.availability.collect { updated ->
                val changed = (previous.keys + updated.keys).filterTo(mutableSetOf()) {
                    (previous[it] == true) != (updated[it] == true)
                }
                downloadAdapter.refreshAvailability(changed)
                if (::historyAdapter.isInitialized) historyAdapter.refreshAvailability(changed)
                previous = updated
            }
        }
    }

    private fun initLibrary() {
        libraryAdapter =
            LibraryAdapter(
                onPlayClicked = { item ->
                    val uriOrPath = item.contentUri ?: item.filePath
                    if (!uriOrPath.isNullOrEmpty()) {
                        FileUtils.openFile(activity, uriOrPath)
                    }
                },
                onShareClicked = { item ->
                    val uriOrPath = item.contentUri ?: item.filePath
                    if (!uriOrPath.isNullOrEmpty()) {
                        FileUtils.shareFile(activity, uriOrPath)
                    }
                },
                onDeleteClicked = { item ->
                    confirmDeleteLibraryItem(item)
                },
                onItemClick = {
                    if (isSelectionMode) {
                        triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
                        val count = libraryAdapter.selectedIds.size
                        if (count == 0) {
                            exitSelectionMode()
                        } else {
                            updateSelectionCount(count)
                        }
                    }
                },
                onItemLongClick = { item ->
                    if (!isSelectionMode) {
                        enterSelectionMode(SelectionType.LIBRARY, item.id)
                        true
                    } else false
                }
            )

        binding.rvLibrary.apply {
            layoutManager = LinearLayoutManager(activity)
            adapter = libraryAdapter
        }

        val librarySwipeHelper = ItemTouchHelper(SwipeToDeleteCallback(activity, canSwipe = {
            prefs.swipeToDelete && !isSelectionMode
        }) { position, _ ->
            val adapter = libraryAdapter
            val item = adapter.currentList.getOrNull(position) ?: return@SwipeToDeleteCallback
            val reset = { adapter.refreshRow(item.id) }
            if (!prefs.swipeToDelete || isSelectionMode) {
                reset()
                return@SwipeToDeleteCallback
            }
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            if (prefs.confirmSwipeDelete) {
                MaterialAlertDialogBuilder(activity)
                    .setTitle(R.string.delete)
                    .setMessage(activity.getString(R.string.delete_file_confirm, item.title))
                    .setPositiveButton(R.string.delete) { _, _ -> deleteLibraryItem(item, reset) }
                    .setNegativeButton(R.string.cancel) { _, _ -> reset() }
                    .setOnCancelListener { reset() }
                    .show()
            } else deleteLibraryItem(item, reset)
        })
        librarySwipeHelper.attachToRecyclerView(binding.rvLibrary)

        binding.btnLibraryRefresh.applyPressEffect()
        binding.btnLibraryRefresh.setOnClickListener {
            binding.btnLibraryRefresh.animate().rotationBy(360f).setDuration(400).start()
            LibraryManager.refresh(activity, prefs.downloadDir)
        }

        binding.btnLibraryOpenFolder.applyPressEffect()
        binding.btnLibraryOpenFolder.setOnClickListener {
            FileUtils.openFolder(activity, prefs.downloadDir)
        }

        val filter = SeriesFilter<LibraryItem>(binding.filterLibrary, { it.series }, libraryAdapter::submitList)
        uiCollectors += activity.lifecycleScope.launch {
            LibraryManager.items.collect { list ->
                filter.submit(list)
                if (list.isEmpty()) {
                    binding.llLibraryEmpty.visibility = View.VISIBLE
                    binding.rvLibrary.visibility = View.GONE
                    binding.tvLibraryCount.text = activity.getString(R.string.video_count, 0)
                } else {
                    binding.llLibraryEmpty.visibility = View.GONE
                    binding.rvLibrary.visibility = View.VISIBLE
                    val totalBytes = list.sumOf { it.fileSizeBytes }
                    val sizeStr = FileUtils.formatFileSize(totalBytes)
                    binding.tvLibraryCount.text =
                        "${activity.getString(R.string.video_count, list.size)} • $sizeStr"
                }
            }
        }
    }

    private fun confirmDeleteLibraryItem(item: LibraryItem) {
        MaterialAlertDialogBuilder(activity)
            .setTitle(R.string.delete)
            .setMessage(activity.getString(R.string.delete_file_confirm, item.title))
            .setPositiveButton(R.string.delete) { _, _ -> deleteLibraryItem(item) }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun deleteLibraryItem(item: LibraryItem, restoreSwipe: () -> Unit = {}) {
        activity.lifecycleScope.launch {
            val deleted = LibraryManager.deleteItem(activity, item)
            if (!deleted) restoreSwipe()
            ToastManager.show(binding.toastContainer,
                activity.getString(if (deleted) R.string.file_deleted else R.string.file_delete_failed),
                isError = !deleted)
        }
    }

    private fun initHistory() {
        historyAdapter =
            HistoryAdapter(
                onRedownloadClicked = requestHistoryRetry,
                onPlayClicked = { item ->
                    val uriOrPath = item.contentUri ?: item.savedPath
                    if (!uriOrPath.isNullOrEmpty()) {
                        FileUtils.openFile(activity, uriOrPath)
                    } else {
                        FileUtils.openFolder(activity, prefs.downloadDir)
                    }
                },
                onCopyClicked = { item ->
                    val source = HistoryLinks.copySource(item)
                    if (source == null) {
                        ToastManager.show(binding.toastContainer, activity.getString(R.string.original_link_missing))
                        return@HistoryAdapter
                    }
                    copyLink(source)
                    ToastManager.show(binding.toastContainer, activity.getString(R.string.link_copied))
                },
                onDeleteClicked = { item -> HistoryManager.remove(activity, item.id) },
                onItemClick = {
                    if (isSelectionMode) {
                        triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
                        val count = historyAdapter.selectedIds.size
                        if (count == 0) {
                            exitSelectionMode()
                        } else {
                            updateSelectionCount(count)
                        }
                    }
                },
                onItemLongClick = { item ->
                    if (!isSelectionMode && !DownloadManager.isActive(item.id)) {
                        enterSelectionMode(SelectionType.HISTORY, item.id)
                        true
                    } else false
                }
            )

        binding.rvHistory.apply {
            layoutManager = LinearLayoutManager(activity)
            adapter = historyAdapter
        }

        val historySwipeHelper = ItemTouchHelper(SwipeToDeleteCallback(activity, canSwipe = { position ->
            prefs.swipeToDelete && !isSelectionMode &&
                historyAdapter.currentList.getOrNull(position)?.let { !DownloadManager.isActive(it.id) } == true
        }) { position, _ ->
            val adapter = historyAdapter
            val item = adapter.currentList.getOrNull(position) ?: return@SwipeToDeleteCallback
            val reset = { adapter.refreshRow(item.id) }
            if (!prefs.swipeToDelete || isSelectionMode || DownloadManager.isActive(item.id)) {
                reset()
                return@SwipeToDeleteCallback
            }
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            if (prefs.confirmSwipeDelete) {
                MaterialAlertDialogBuilder(activity)
                    .setTitle(R.string.delete)
                    .setMessage(activity.getString(R.string.delete_file_confirm, item.title))
                    .setPositiveButton(R.string.delete) { _, _ ->
                        HistoryManager.remove(activity, item.id)
                        ToastManager.show(binding.toastContainer, activity.getString(R.string.item_deleted))
                    }
                    .setNegativeButton(R.string.cancel) { _, _ -> reset() }
                    .setOnCancelListener { reset() }
                    .show()
            } else {
                HistoryManager.remove(activity, item.id)
                ToastManager.show(binding.toastContainer, activity.getString(R.string.item_deleted))
            }
        })
        historySwipeHelper.attachToRecyclerView(binding.rvHistory)

        binding.btnHistoryClearAll.applyPressEffect()
        binding.btnHistoryClearAll.setOnClickListener {
            MaterialAlertDialogBuilder(activity)
                .setTitle(R.string.clear_history)
                .setMessage(R.string.clear_history_confirm)
                .setPositiveButton(R.string.clear_history) { _, _ -> HistoryManager.clear(activity) }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        val filter = SeriesFilter<HistoryItem>(binding.filterHistory, { it.series }, historyAdapter::submitList)
        uiCollectors += activity.lifecycleScope.launch {
            HistoryManager.items.collect { list ->
                filter.submit(list)
                if (list.isEmpty()) {
                    binding.llHistoryEmpty.visibility = View.VISIBLE
                    binding.rvHistory.visibility = View.GONE
                    binding.tvHistoryCount.text = ""
                } else {
                    binding.llHistoryEmpty.visibility = View.GONE
                    binding.rvHistory.visibility = View.VISIBLE
                    binding.tvHistoryCount.text = activity.getString(R.string.video_count, list.size)
                }
            }
        }
    }

    private fun initSelectionBar() {
        binding.btnSelectionClose.setOnClickListener {
            exitSelectionMode()
        }

        binding.btnSelectionDelete.setOnClickListener {
            val count = if (selectionType == SelectionType.DOWNLOADS) {
                downloadAdapter.selectedIds.size
            } else if (selectionType == SelectionType.LIBRARY) {
                libraryAdapter.selectedIds.size
            } else {
                historyAdapter.selectedIds.size
            }
            if (count == 0) return@setOnClickListener
            if (selectionType == SelectionType.DOWNLOADS && downloadAdapter.selectedIds.any { DownloadManager.isActive(it) }) return@setOnClickListener
            if (selectionType == SelectionType.HISTORY && historyAdapter.selectedIds.any { DownloadManager.isActive(it) }) return@setOnClickListener

            MaterialAlertDialogBuilder(activity)
                .setTitle(R.string.delete)
                .setMessage(if (selectionType == SelectionType.DOWNLOADS)
                    activity.getString(R.string.remove_downloads_confirm, count)
                    else activity.getString(R.string.delete_selected_confirm, count))
                .setPositiveButton(R.string.delete) { _, _ ->
                    if (selectionType == SelectionType.DOWNLOADS) {
                        downloadAdapter.selectedIds.toSet().forEach { DownloadManager.removeDownload(it) }
                    } else if (selectionType == SelectionType.LIBRARY) {
                        val itemsToDelete = libraryAdapter.currentList.filter { it.id in libraryAdapter.selectedIds }
                        activity.lifecycleScope.launch {
                            val deleted = itemsToDelete.count { LibraryManager.deleteItem(activity, it) }
                            val message = if (deleted == 0) activity.getString(R.string.file_delete_failed)
                                else activity.getString(R.string.items_deleted, deleted)
                            ToastManager.show(binding.toastContainer, message, isError = deleted == 0)
                        }
                    } else if (selectionType == SelectionType.HISTORY) {
                        val idsToDelete = historyAdapter.selectedIds.toSet()
                        for (id in idsToDelete) {
                            HistoryManager.remove(activity, id)
                        }
                        ToastManager.show(
                            binding.toastContainer,
                            activity.getString(R.string.items_deleted, idsToDelete.size)
                        )
                    }
                    exitSelectionMode()
                }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        binding.btnSelectionShare.setOnClickListener {
            if (selectionType != SelectionType.LIBRARY) return@setOnClickListener
            val selectedUris = ArrayList<Uri>()
            val items = libraryAdapter.currentList.filter { it.id in libraryAdapter.selectedIds }
            for (item in items) {
                val pathOrUri = item.contentUri ?: item.filePath ?: continue
                if (pathOrUri.startsWith("content://")) {
                    selectedUris.add(Uri.parse(pathOrUri))
                } else {
                    val file = File(pathOrUri)
                    if (file.exists()) {
                        val uri = FileProvider.getUriForFile(
                            activity,
                            "${activity.packageName}.fileprovider",
                            file
                        )
                        selectedUris.add(uri)
                    }
                }
            }
            if (selectedUris.isNotEmpty()) {
                val shareIntent = Intent(Intent.ACTION_SEND_MULTIPLE).apply {
                    type = "video/*"
                    putParcelableArrayListExtra(Intent.EXTRA_STREAM, selectedUris)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                activity.startActivity(Intent.createChooser(shareIntent, activity.getString(R.string.share_file)))
            }
        }
    }

    private fun enterSelectionMode(type: SelectionType, initialId: String) {
        isSelectionMode = true
        selectionType = type
        triggerHaptic(HapticFeedbackConstants.LONG_PRESS)

        binding.headerBar.visibility = View.GONE
        binding.selectionBar.visibility = View.VISIBLE

        if (type == SelectionType.DOWNLOADS) {
            binding.btnSelectionShare.visibility = View.GONE
            downloadAdapter.isSelectionMode = true
            downloadAdapter.selectedIds.clear()
            downloadAdapter.selectedIds.add(initialId)
            downloadAdapter.notifyItemRangeChanged(0, downloadAdapter.itemCount)
            updateSelectionCount(1)
        } else if (type == SelectionType.LIBRARY) {
            binding.btnSelectionShare.visibility = View.VISIBLE
            libraryAdapter.isSelectionMode = true
            libraryAdapter.selectedIds.clear()
            libraryAdapter.selectedIds.add(initialId)
            libraryAdapter.refreshRow(initialId)
            updateSelectionCount(1)
        } else {
            binding.btnSelectionShare.visibility = View.GONE
            historyAdapter.isSelectionMode = true
            historyAdapter.selectedIds.clear()
            historyAdapter.selectedIds.add(initialId)
            historyAdapter.refreshRow(initialId)
            updateSelectionCount(1)
        }
    }

    fun exitSelectionMode() {
        isSelectionMode = false
        selectionType = SelectionType.NONE

        binding.selectionBar.visibility = View.GONE
        binding.headerBar.visibility = View.VISIBLE

        downloadAdapter.clearSelection()
        libraryAdapter.isSelectionMode = false
        libraryAdapter.clearSelection()

        historyAdapter.isSelectionMode = false
        historyAdapter.clearSelection()
    }

    private fun updateSelectionCount(count: Int) {
        binding.tvSelectionTitle.text = activity.getString(R.string.selected_count, count)
    }

}
