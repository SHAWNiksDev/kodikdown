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
import com.shawniks.kodikdown.databinding.ItemHistoryBinding
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class HistoryAdapter(
    private val onRedownloadClicked: (HistoryItem) -> Unit,
    private val onPlayClicked: (HistoryItem) -> Unit,
    private val onCopyClicked: (HistoryItem) -> Unit,
    private val onDeleteClicked: (HistoryItem) -> Unit
) : ListAdapter<HistoryItem, HistoryAdapter.HistoryViewHolder>(DiffCallback) {

    private val dateFormat = SimpleDateFormat("dd MMM, HH:mm", Locale.getDefault())

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
            val context = binding.root.context
            binding.tvHistoryTitle.text = item.title

            // Status Badge
            when (item.status) {
                DownloadStatus.FINISHED -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.status_completed)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_success))
                }
                DownloadStatus.CANCELLED -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.cancelled)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_warning))
                }
                DownloadStatus.FAILED -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.failed, "").trimEnd(':', ' ')
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_danger))
                }
                else -> {
                    binding.tvHistoryStatus.text = context.getString(R.string.starting)
                    binding.tvHistoryStatus.setTextColor(ContextCompat.getColor(context, R.color.dark_accent))
                }
            }

            // Metadata text
            val metaParts = mutableListOf<String>()
            if (item.quality > 0) metaParts.add("${item.quality}p")
            if (!item.translation.isNullOrEmpty()) metaParts.add(item.translation)
            if (item.fileSize > 0) metaParts.add(FileUtils.formatFileSize(item.fileSize))
            if (item.timestamp > 0) metaParts.add(dateFormat.format(Date(item.timestamp)))

            binding.tvHistoryMeta.text = metaParts.joinToString(" • ")

            // Error display
            if (!item.errorMessage.isNullOrEmpty() && item.status == DownloadStatus.FAILED) {
                binding.tvHistoryError.visibility = View.VISIBLE
                binding.tvHistoryError.text = item.errorMessage
            } else {
                binding.tvHistoryError.visibility = View.GONE
            }

            // Check if file exists on disk or MediaStore contentUri for "Play" button
            val hasFile = (!item.savedPath.isNullOrEmpty() && File(item.savedPath!!).exists()) || !item.contentUri.isNullOrEmpty()
            binding.btnHistoryPlay.visibility = if (hasFile) View.VISIBLE else View.GONE

            binding.btnHistoryRedownload.setOnClickListener { onRedownloadClicked(item) }
            binding.btnHistoryPlay.setOnClickListener { onPlayClicked(item) }
            binding.btnHistoryCopy.setOnClickListener { onCopyClicked(item) }
            binding.btnHistoryDelete.setOnClickListener { onDeleteClicked(item) }
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
