package com.shawniks.kodikdown.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.HistoryItem
import com.shawniks.kodikdown.data.MediaFiles
import com.shawniks.kodikdown.databinding.ItemHistoryBinding
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.util.FileUtils
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class HistoryAdapter(
    private val onRedownloadClicked: (HistoryItem) -> Unit,
    private val onPlayClicked: (HistoryItem) -> Unit,
    private val onCopyClicked: (HistoryItem) -> Unit,
    private val onDeleteClicked: (HistoryItem) -> Unit,
    private val onItemClick: (HistoryItem) -> Unit = {},
    private val onItemLongClick: (HistoryItem) -> Boolean = { false }
) : ListAdapter<HistoryItem, HistoryAdapter.HistoryViewHolder>(DiffCallback) {

    private val dateFormat = SimpleDateFormat("dd MMM, HH:mm", Locale.getDefault())

    var isSelectionMode: Boolean = false
        set(value) {
            if (field == value) return
            field = value
            notifyItemRangeChanged(0, itemCount)
        }

    val selectedIds: MutableSet<String> = mutableSetOf()

    fun refreshAvailability(changed: Set<MediaFiles.Reference>) {
        if (changed.isEmpty()) return
        currentList.forEachIndexed { index, item ->
            if (item.status == DownloadStatus.FINISHED && MediaFiles.Reference(item.savedPath, item.contentUri) in changed) {
                notifyItemChanged(index)
            }
        }
    }

    fun selectAll() {
        selectedIds.clear()
        currentList.filterNot { DownloadManager.isActive(it.id) }.forEach { selectedIds.add(it.id) }
        notifyItemRangeChanged(0, itemCount)
    }

    fun clearSelection() {
        selectedIds.clear()
        notifyItemRangeChanged(0, itemCount)
    }

    private fun toggleSelection(id: String) {
        if (selectedIds.contains(id)) {
            selectedIds.remove(id)
        } else {
            selectedIds.add(id)
        }
        refreshRow(id)
    }

    fun refreshRow(id: String) {
        val position = currentList.indexOfFirst { it.id == id }
        if (position >= 0) notifyItemChanged(position)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): HistoryViewHolder {
        val binding = ItemHistoryBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return HistoryViewHolder(binding)
    }

    override fun onBindViewHolder(holder: HistoryViewHolder, position: Int) {
        holder.bind(getItem(position))
    }

    inner class HistoryViewHolder(private val binding: ItemHistoryBinding) : RecyclerView.ViewHolder(binding.root) {
        init {
            binding.btnHistoryRedownload.applyPressEffect()
            binding.btnHistoryPlay.applyPressEffect()
            binding.btnHistoryCopy.applyPressEffect()
            binding.btnHistoryDelete.applyPressEffect()
        }

        fun bind(item: HistoryItem) {
            val active = DownloadManager.isActive(item.id)
            val available = MediaFiles.isAvailable(item.savedPath, item.contentUri)
            val isSelected = selectedIds.contains(item.id)
            val context = binding.root.context
            binding.tvHistoryTitle.text = listOfNotNull(item.series, item.title).joinToString(" · ")

            when (item.status) {
                DownloadStatus.FINISHED -> {
                    binding.tvHistoryStatus.text = context.getString(if (available) R.string.status_completed else R.string.file_missing)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, if (available) R.color.dark_success else R.color.dark_text_muted))
                }
                DownloadStatus.CANCELLED -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.cancelled)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_warning))
                }
                DownloadStatus.FAILED -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.failed, "").trimEnd(':', ' ')
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_danger))
                }
                DownloadStatus.DOWNLOADING -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.status_downloading)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_accent))
                }
                DownloadStatus.ASSEMBLING -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.stage_processing)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_accent))
                }
                else -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.queued)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_accent))
                }
            }

            if (isSelectionMode) {
                binding.ivSelectCheck.visibility = View.VISIBLE
                binding.ivSelectCheck.setImageResource(
                    if (isSelected) R.drawable.ic_checkbox_checked else R.drawable.ic_checkbox_unchecked
                )
                binding.root.setBackgroundResource(
                    if (isSelected) R.drawable.bg_card_selected else R.drawable.bg_card
                )
            } else {
                binding.ivSelectCheck.visibility = View.GONE
                binding.root.setBackgroundResource(R.drawable.bg_card)
            }

            val metaParts = mutableListOf<String>()
            if (item.quality > 0) metaParts.add("${item.quality}p")
            if (!item.translation.isNullOrEmpty()) metaParts.add(item.translation)
            if (item.fileSize > 0) metaParts.add(FileUtils.formatFileSize(item.fileSize))
            if (item.timestamp > 0) metaParts.add(dateFormat.format(Date(item.timestamp)))

            binding.tvHistoryMeta.text = metaParts.joinToString(" • ")

            if (!item.errorMessage.isNullOrEmpty() && item.status == DownloadStatus.FAILED) {
                binding.tvHistoryError.visibility = View.VISIBLE
                binding.tvHistoryError.text = item.errorMessage
            } else {
                binding.tvHistoryError.visibility = View.GONE
            }

            binding.btnHistoryPlay.visibility = if (available && item.status == DownloadStatus.FINISHED) View.VISIBLE else View.GONE
            binding.btnHistoryDelete.isEnabled = !active
            binding.btnHistoryDelete.alpha = if (active) 0.35f else 1f
            binding.btnHistoryRedownload.isEnabled = !active
            binding.btnHistoryRedownload.alpha = if (active) 0.35f else 1f

            binding.root.setOnClickListener {
                if (isSelectionMode && !active) {
                    toggleSelection(item.id)
                    onItemClick(item)
                }
            }

            binding.root.setOnLongClickListener {
                if (active) false else onItemLongClick(item)
            }

            binding.btnHistoryRedownload.setOnClickListener { if (!DownloadManager.isActive(item.id)) onRedownloadClicked(item) }
            binding.btnHistoryPlay.setOnClickListener { onPlayClicked(item) }
            binding.btnHistoryCopy.setOnClickListener { onCopyClicked(item) }
            binding.btnHistoryDelete.setOnClickListener { if (!DownloadManager.isActive(item.id)) onDeleteClicked(item) }
        }
    }

    companion object {
        private val DiffCallback = object : DiffUtil.ItemCallback<HistoryItem>() {
            override fun areItemsTheSame(oldItem: HistoryItem, newItem: HistoryItem): Boolean =
                oldItem.id == newItem.id

            override fun areContentsTheSame(oldItem: HistoryItem, newItem: HistoryItem): Boolean =
                oldItem == newItem
        }
    }
}
