package com.shawniks.kodikdown.ui

import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Spinner
import com.shawniks.kodikdown.R

class SeriesFilter<T>(
    private val field: Spinner,
    private val seriesOf: (T) -> String?,
    private val display: (List<T>) -> Unit,
) {
    private var entries = emptyList<T>()
    private var groups = emptyList<String>()

    init {
        field.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                render()
            }
        }
    }

    fun submit(list: List<T>) {
        val selected = groups.getOrNull(field.selectedItemPosition - 1)
        entries = list
        val options = list.mapNotNull(seriesOf).distinct()
        if (options != groups) {
            groups = options
            val labels = listOf(field.context.getString(R.string.all_series_folders)) + groups
            field.adapter = ArrayAdapter(field.context, android.R.layout.simple_spinner_dropdown_item, labels)
            field.setSelection(groups.indexOf(selected) + 1)
        }
        field.visibility = if (groups.isEmpty()) View.GONE else View.VISIBLE
        render()
    }

    private fun render() {
        val group = groups.getOrNull(field.selectedItemPosition - 1)
        display(if (group == null) entries else entries.filter { seriesOf(it) == group })
    }
}
