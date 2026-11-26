package com.shawniks.kodikdown.ui

import android.R as AndroidR
import android.content.Context
import android.graphics.BitmapFactory
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.FavoriteSeries
import com.shawniks.kodikdown.kodik.Catalog
import com.shawniks.kodikdown.kodik.CatalogClient
import com.shawniks.kodikdown.kodik.CatalogChoice
import com.shawniks.kodikdown.kodik.CatalogEpisode

class CatalogDialog(
    private val context: Context,
    private val catalog: Catalog,
    private val poster: ByteArray?,
    private val defaultQuality: Int?,
    private val groupSeries: Boolean,
    private val preferMp4: Boolean,
    private val favorite: FavoriteSeries?,
    private val savedEpisodes: Set<String>,
    private val saveFavorite: (FavoriteSeries) -> Unit,
    private val enqueue: (CatalogChoice, List<CatalogEpisode>, Int, Boolean) -> Unit,
) {
    fun show() {
        val content = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(8), dp(20), dp(12))
        }

        val details = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        val description = catalog.description.trim()
        poster?.let { BitmapFactory.decodeByteArray(it, 0, it.size) }?.let { bitmap ->
            details.addView(ImageView(context).apply {
                setImageBitmap(bitmap)
                scaleType = ImageView.ScaleType.FIT_CENTER
            }, LinearLayout.LayoutParams(dp(66), dp(92)).apply { marginEnd = dp(12) })
        }
        if (description.isNotEmpty()) details.addView(TextView(context).apply {
            text = description.take(360) + if (description.length > 360) "…" else ""
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        if (details.childCount > 0) {
            content.addView(Button(context).apply {
                setText(R.string.hide_details)
                setOnClickListener {
                    val visible = details.visibility == View.VISIBLE
                    details.visibility = if (visible) View.GONE else View.VISIBLE
                    setText(if (visible) R.string.show_details else R.string.hide_details)
                }
            })
            content.addView(details)
        }

        val players = catalog.choices.map { it.player }.distinct().sortedBy { !it.equals("Kodik", true) }
        val player = spinner(content, R.string.catalog_player)
        val voice = spinner(content, R.string.translation)
        val quality = spinner(content, R.string.quality)
        val heights = listOf(1080, 720, 480, 360, 240, 144)
        player.items(players)
        quality.items(heights.map { "${it}p" })
        quality.setSelection(heights.indexOf(defaultQuality).coerceAtLeast(0))

        val group = CheckBox(context).apply {
            setText(R.string.group_series)
            isChecked = groupSeries
        }
        content.addView(group)
        val favoriteButton = Button(context).apply { setText(R.string.save_favorite) }
        content.addView(favoriteButton)
        val count = TextView(context).apply { setPadding(0, dp(8), 0, 0) }
        content.addView(count)
        val selectAll = Button(context)
        content.addView(selectAll)
        val episodes = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        content.addView(episodes)
        val scroll = ScrollView(context).apply { addView(content) }

        var choices = emptyList<CatalogChoice>()
        var choice: CatalogChoice? = null
        val selected = linkedSetOf<String>()
        val favoriteChoice = favorite?.let { saved ->
            catalog.choices.firstOrNull { it.player == saved.player && it.voice == saved.voice }
        }
        val dialog = MaterialAlertDialogBuilder(context).setTitle(catalog.title).setView(scroll)
            .setNegativeButton(AndroidR.string.cancel, null)
            .setPositiveButton(R.string.download, null)
            .create()

        fun updateCount() {
            val items = choice?.episodes.orEmpty()
            val checked = items.count { it.number in selected }
            count.text = context.getString(R.string.catalog_selected, checked, items.size)
            selectAll.setText(if (items.isNotEmpty() && checked == items.size) R.string.clear_selection else R.string.select_all_episodes)
            dialog.getButton(AlertDialog.BUTTON_POSITIVE)?.isEnabled = checked > 0
        }

        fun showEpisodes(index: Int) {
            val next = choices.getOrNull(index)
            if (next != choice) {
                selected.clear()
                if (next == favoriteChoice && next != null) {
                    selected.addAll(next.episodes.filterNot { it.url in savedEpisodes }.map { it.number })
                } else {
                    next?.episodes?.firstOrNull()?.let { selected.add(it.number) }
                }
            }
            choice = next
            val entries = choice?.episodes.orEmpty()
            episodes.removeAllViews()
            entries.forEach { episode ->
                episodes.addView(CheckBox(context).apply {
                    text = context.getString(R.string.episode_number, episode.number)
                    isChecked = episode.number in selected
                    setOnCheckedChangeListener { _, checked ->
                        if (checked) selected.add(episode.number) else selected.remove(episode.number)
                        updateCount()
                    }
                })
            }
            updateCount()
        }

        fun showVoices(index: Int) {
            val oldVoice = choice?.voice
            choices = catalog.choices.filter { it.player == players.getOrNull(index) }
            voice.items(choices.map { it.voice.ifBlank { "—" } })
            val next = choices.indexOfFirst { it.voice == (oldVoice ?: favorite?.voice) }.coerceAtLeast(0)
            voice.setSelection(next)
            showEpisodes(next)
        }

        player.onPick(::showVoices)
        voice.onPick(::showEpisodes)
        favoriteButton.setOnClickListener {
            val current = choice ?: return@setOnClickListener
            saveFavorite(FavoriteSeries(CatalogClient.normalize(catalog.url), catalog.title,
                current.player, current.voice, heights[quality.selectedItemPosition], group.isChecked, preferMp4))
            favoriteButton.setText(R.string.favorite_saved)
        }
        selectAll.setOnClickListener {
            val boxes = (0 until episodes.childCount).map { episodes.getChildAt(it) as CheckBox }
            val checked = boxes.any { !it.isChecked }
            boxes.forEach { it.isChecked = checked }
        }
        dialog.setOnShowListener {
            updateCount()
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val current = choice ?: return@setOnClickListener
                val picked = current.episodes.filter { it.number in selected }
                if (picked.isEmpty()) return@setOnClickListener
                enqueue(current, picked, heights[quality.selectedItemPosition], group.isChecked)
                dialog.dismiss()
            }
        }
        val playerIndex = players.indexOf(favorite?.player).coerceAtLeast(0)
        player.setSelection(playerIndex)
        showVoices(playerIndex)
        if (favorite != null && favoriteChoice == null) {
            content.addView(TextView(context).apply { setText(R.string.favorite_source_missing) }, 0)
        }
        dialog.show()
    }

    private fun spinner(layout: LinearLayout, label: Int): Spinner {
        val caption = TextView(context).apply { setText(label) }
        layout.addView(caption)
        val field = Spinner(context).apply {
            contentDescription = context.getString(label)
            minimumHeight = dp(44)
        }
        layout.addView(field, LinearLayout.LayoutParams(-1, -2))
        return field
    }

    private fun Spinner.items(items: List<String>) {
        adapter = object : ArrayAdapter<String>(context, AndroidR.layout.simple_spinner_dropdown_item, items) {
            override fun getView(position: Int, previous: View?, parent: ViewGroup): View =
                brand(super.getView(position, previous, parent), items[position])

            override fun getDropDownView(position: Int, previous: View?, parent: ViewGroup): View =
                brand(super.getDropDownView(position, previous, parent), items[position])
        }
    }

    private fun brand(view: View, name: String): View {
        val resource = when (name.lowercase().filter { it.isLetterOrDigit() }) {
            "cvh" -> R.drawable.brand_cvh
            "shizaproject" -> R.drawable.brand_shiza
            "anidub" -> R.drawable.brand_anidub
            "animedia" -> R.drawable.brand_animedia
            "anilibria", "aniliberty" -> R.drawable.brand_aniliberty
            "kodik" -> R.drawable.ic_play
            else -> 0
        }
        (view as? TextView)?.apply {
            val image = resource.takeIf { it != 0 }?.let(context::getDrawable)
            image?.setBounds(0, 0, dp(18), dp(18))
            setCompoundDrawablesRelative(image, null, null, null)
            compoundDrawablePadding = dp(8)
        }
        return view
    }

    private fun Spinner.onPick(pick: (Int) -> Unit) {
        onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) = pick(position)
        }
    }

    private fun dp(value: Int) = (context.resources.displayMetrics.density * value).toInt()
}
