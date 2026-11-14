package com.shawniks.kodikdown.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.LibraryItem
import com.shawniks.kodikdown.databinding.ItemLibraryBinding
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.util.FileUtils
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class LibraryAdapter(
    private val onPlayClicked: (LibraryItem) -> Unit,
    private val onShareClicked: (LibraryItem) -> Unit,
    private val onDeleteClicked: (LibraryItem) -> Unit,
    private val onItemClick: (LibraryItem) -> Unit = {},
    private val onItemLongClick: (LibraryItem) -> Boolean = { false }
) : ListAdapter<LibraryItem, LibraryAdapter.LibraryViewHolder>(DiffCallback) {

    private val dateFormat = SimpleDateFormat("dd MMM, HH:mm", Locale.getDefault())

    var isSelectionMode: Boolean = false
        set(value) {
            field = value
            notifyDataSetChanged()
        }

    val selectedIds: MutableSet<String> = mutableSetOf()

    fun selectAll() {
        selectedIds.clear()
        currentList.forEach { selectedIds.add(it.id) }
        notifyDataSetChanged()
    }

    fun clearSelection() {
        selectedIds.clear()
        notifyDataSetChanged()
    }

    fun toggleSelection(id: String) {
        if (selectedIds.contains(id)) {
            selectedIds.remove(id)
        } else {
            selectedIds.add(id)
        }
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): LibraryViewHolder {
        val binding = ItemLibraryBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return LibraryViewHolder(binding)
    }

    override fun onBindViewHolder(holder: LibraryViewHolder, position: Int) {
        holder.bind(getItem(position))
    }

    inner class LibraryViewHolder(private val binding: ItemLibraryBinding) : RecyclerView.ViewHolder(binding.root) {
        init {
            binding.btnPlay.applyPressEffect()
            binding.btnShare.applyPressEffect()
            binding.btnDelete.applyPressEffect()
        }

        fun bind(item: LibraryItem) {
            val isSelected = selectedIds.contains(item.id)

            binding.tvTitle.text = item.title

            val sizeStr = FileUtils.formatFileSize(item.fileSizeBytes)
            val dateStr = if (item.dateModified > 0) dateFormat.format(Date(item.dateModified)) else ""
            binding.tvDetails.text = if (dateStr.isNotEmpty()) "$sizeStr • $dateStr" else sizeStr

            if (item.quality != null && item.quality > 0) {
                binding.tvQualityBadge.visibility = View.VISIBLE
                binding.tvQualityBadge.text = "${item.quality}p"
            } else {
                binding.tvQualityBadge.visibility = View.VISIBLE
                binding.tvQualityBadge.text = if (item.isMp4) "MP4" else "VIDEO"
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

            binding.root.setOnClickListener {
                if (isSelectionMode) {
                    toggleSelection(item.id)
                    onItemClick(item)
                } else {
                    onPlayClicked(item)
                }
            }

            binding.root.setOnLongClickListener {
                onItemLongClick(item)
            }

            binding.btnPlay.setOnClickListener { onPlayClicked(item) }
            binding.btnShare.setOnClickListener { onShareClicked(item) }
            binding.btnDelete.setOnClickListener { onDeleteClicked(item) }
        }
    }

    companion object {
        private val DiffCallback = object : DiffUtil.ItemCallback<LibraryItem>() {
            override fun areItemsTheSame(oldItem: LibraryItem, newItem: LibraryItem): Boolean =
                oldItem.id == newItem.id

            override fun areContentsTheSame(oldItem: LibraryItem, newItem: LibraryItem): Boolean =
                oldItem == newItem
        }
    }
}
