package com.shawniks.kodikdown.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.DownloadItem
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.databinding.ItemDownloadBinding
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.util.FileUtils
import java.io.File

class DownloadAdapter(
    private val onCancelClicked: (DownloadItem) -> Unit,
    private val onOpenClicked: (DownloadItem) -> Unit,
    private val onShareClicked: (DownloadItem) -> Unit
) : ListAdapter<DownloadItem, DownloadAdapter.ViewHolder>(DiffCallback) {

    object DiffCallback : DiffUtil.ItemCallback<DownloadItem>() {
        override fun areItemsTheSame(oldItem: DownloadItem, newItem: DownloadItem): Boolean {
            return oldItem.id == newItem.id
        }

        override fun areContentsTheSame(oldItem: DownloadItem, newItem: DownloadItem): Boolean {
            return oldItem == newItem
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemDownloadBinding.inflate(
            LayoutInflater.from(parent.context), parent, false
        )
        return ViewHolder(binding)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.bind(getItem(position))
    }

    inner class ViewHolder(private val binding: ItemDownloadBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(item: DownloadItem) {
            val context = binding.root.context

            binding.tvTitle.text = item.title
            val qualitySuffix = if (item.isMp4) " • MP4" else ""
            binding.tvQualityBadge.text = "${item.quality}p$qualitySuffix"

            binding.btnCancel.applyPressEffect()
            binding.btnOpen.applyPressEffect()
            binding.btnShare.applyPressEffect()

            binding.btnCancel.setOnClickListener { onCancelClicked(item) }
            binding.btnOpen.setOnClickListener { onOpenClicked(item) }
            binding.btnShare.setOnClickListener { onShareClicked(item) }

            when (item.status) {
                DownloadStatus.QUEUED -> {
                    binding.cardLayout.setBackgroundResource(R.drawable.bg_card)
                    binding.progressBar.visibility = View.VISIBLE
                    binding.progressBar.isIndeterminate = true
                    binding.btnCancel.visibility = View.VISIBLE
                    binding.layoutActions.visibility = View.GONE
                    binding.tvStatus.text = context.getString(R.string.queued)
                    binding.tvStatus.setTextColor(getThemeColor(context, R.attr.app_text_muted))
                }
                DownloadStatus.DOWNLOADING -> {
                    binding.cardLayout.setBackgroundResource(R.drawable.bg_card)
                    binding.progressBar.visibility = View.VISIBLE
                    binding.progressBar.isIndeterminate = false
                    val percent = (item.progress * 100).toInt()
                    binding.progressBar.progress = percent
                    binding.btnCancel.visibility = View.VISIBLE
                    binding.layoutActions.visibility = View.GONE

                    val speedText = formatSpeed(item.speedBytesPerSec)
                    val sizeText = formatSizes(item.downloadedBytes, item.totalBytes)
                    val etaText = item.etaSeconds?.let { formatEta(context, it) } ?: ""

                    val statusParts = listOfNotNull(
                        sizeText.takeIf { it.isNotEmpty() },
                        speedText.takeIf { it.isNotEmpty() },
                        etaText.takeIf { it.isNotEmpty() }
                    )
                    binding.tvStatus.text = statusParts.joinToString(" • ")
                    binding.tvStatus.setTextColor(getThemeColor(context, R.attr.app_text_muted))
                }
                DownloadStatus.ASSEMBLING -> {
                    binding.cardLayout.setBackgroundResource(R.drawable.bg_card)
                    binding.progressBar.visibility = View.VISIBLE
                    binding.progressBar.isIndeterminate = true
                    binding.btnCancel.visibility = View.VISIBLE
                    binding.layoutActions.visibility = View.GONE
                    binding.tvStatus.text = context.getString(R.string.stage_processing)
                    binding.tvStatus.setTextColor(getThemeColor(context, R.attr.app_text_muted))
                }
                DownloadStatus.FINISHED -> {
                    binding.cardLayout.setBackgroundResource(R.drawable.bg_card_finished)
                    binding.progressBar.visibility = View.VISIBLE
                    binding.progressBar.isIndeterminate = false
                    binding.progressBar.progress = 100
                    binding.btnCancel.visibility = View.GONE
                    if (binding.layoutActions.visibility != View.VISIBLE) {
                        binding.layoutActions.visibility = View.VISIBLE
                        binding.layoutActions.alpha = 0f
                        binding.layoutActions.animate().alpha(1f).setDuration(250).start()
                    }

                    val savedText = context.getString(R.string.saved_to, item.savedPath ?: item.fileName)
                    binding.tvStatus.text = savedText
                    binding.tvStatus.setTextColor(getThemeColor(context, R.attr.app_success))
                }
                DownloadStatus.FAILED -> {
                    binding.cardLayout.setBackgroundResource(R.drawable.bg_card_failed)
                    binding.progressBar.visibility = View.GONE
                    binding.btnCancel.visibility = View.VISIBLE
                    binding.layoutActions.visibility = View.GONE

                    val err = context.getString(R.string.failed, item.errorMessage ?: "Unknown error")
                    binding.tvStatus.text = err
                    binding.tvStatus.setTextColor(getThemeColor(context, R.attr.app_danger))
                }
                DownloadStatus.CANCELLED -> {
                    binding.cardLayout.setBackgroundResource(R.drawable.bg_card)
                    binding.progressBar.visibility = View.GONE
                    binding.btnCancel.visibility = View.VISIBLE
                    binding.layoutActions.visibility = View.GONE
                    binding.tvStatus.text = context.getString(R.string.cancelled)
                    binding.tvStatus.setTextColor(getThemeColor(context, R.attr.app_text_muted))
                }
            }
        }

        private fun formatSpeed(bytesPerSec: Long): String {
            if (bytesPerSec <= 0) return ""
            return when {
                bytesPerSec >= 1024 * 1024 -> String.format("%.1f MB/s", bytesPerSec.toDouble() / (1024 * 1024))
                bytesPerSec >= 1024 -> String.format("%.0f KB/s", bytesPerSec.toDouble() / 1024)
                else -> "$bytesPerSec B/s"
            }
        }

        private fun formatSizes(downloaded: Long, total: Long?): String {
            val dMb = String.format("%.1f MB", downloaded.toDouble() / (1024 * 1024))
            return if (total != null && total > 0) {
                val tMb = String.format("%.1f MB", total.toDouble() / (1024 * 1024))
                "$dMb / $tMb"
            } else {
                dMb
            }
        }

        private fun formatEta(context: Context, etaSeconds: Long): String {
            if (etaSeconds <= 0) return ""
            val mins = etaSeconds / 60
            val secs = etaSeconds % 60
            val time = String.format("%02d:%02d", mins, secs)
            return context.getString(R.string.eta, time)
        }

        private fun getThemeColor(context: Context, attrRes: Int): Int {
            val typedArray = context.obtainStyledAttributes(intArrayOf(attrRes))
            val color = typedArray.getColor(0, Color.GRAY)
            typedArray.recycle()
            return color
        }
    }
}
