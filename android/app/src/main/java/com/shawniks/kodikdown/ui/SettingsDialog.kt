package com.shawniks.kodikdown.ui

import android.app.Dialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.AppSettings
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.databinding.DialogSettingsBinding
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.util.FileUtils
import java.io.File

class SettingsDialog(
    context: Context,
    private val onSaved: (oldSettings: AppSettings, newSettings: AppSettings) -> Unit,
    private val onPickFolder: () -> Unit
) : BottomSheetDialog(context) {

    private lateinit var binding: DialogSettingsBinding
    private val prefs = PreferencesManager(context)
    private var concurrentCount = 3

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = DialogSettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val settings = prefs.getSettings()
        binding.etDownloadDir.setText(settings.downloadDir)

        // Language Spinner
        val langOptions = listOf(
            context.getString(R.string.language_auto) to "auto",
            context.getString(R.string.language_en) to "en",
            context.getString(R.string.language_ru) to "ru"
        )
        val langAdapter = ArrayAdapter(
            context,
            android.R.layout.simple_spinner_dropdown_item,
            langOptions.map { it.first }
        )
        binding.spLanguage.adapter = langAdapter
        val langIndex = langOptions.indexOfFirst { it.second == settings.language }.coerceAtLeast(0)
        binding.spLanguage.setSelection(langIndex)

        // Theme Spinner
        val themeOptions = listOf(
            context.getString(R.string.theme_auto) to "auto",
            context.getString(R.string.theme_light) to "light",
            context.getString(R.string.theme_dark) to "dark"
        )
        val themeAdapter = ArrayAdapter(
            context,
            android.R.layout.simple_spinner_dropdown_item,
            themeOptions.map { it.first }
        )
        binding.spTheme.adapter = themeAdapter
        val themeIndex = themeOptions.indexOfFirst { it.second == settings.theme }.coerceAtLeast(0)
        binding.spTheme.setSelection(themeIndex)

        // Concurrent count
        concurrentCount = settings.concurrentDownloads
        binding.tvConcurrentCount.text = concurrentCount.toString()

        // Apply interactive animations
        binding.btnMinusConcurrent.applyPressEffect()
        binding.btnPlusConcurrent.applyPressEffect()
        binding.btnBrowseFolder.applyPressEffect()
        binding.btnOpenDir.applyPressEffect()
        binding.btnCloseDialog.applyPressEffect()
        binding.btnSaveSettings.applyPressEffect()

        binding.btnMinusConcurrent.setOnClickListener {
            if (concurrentCount > 1) {
                concurrentCount--
                binding.tvConcurrentCount.text = concurrentCount.toString()
            }
        }
        binding.btnPlusConcurrent.setOnClickListener {
            if (concurrentCount < 5) {
                concurrentCount++
                binding.tvConcurrentCount.text = concurrentCount.toString()
            }
        }

        // Prefer MP4
        binding.cbPreferMp4.isChecked = settings.preferMp4

        // Browse folder
        binding.btnBrowseFolder.setOnClickListener {
            onPickFolder()
        }

        // Open Folder
        binding.btnOpenDir.setOnClickListener {
            val dirPath = binding.etDownloadDir.text.toString().trim().ifEmpty { PreferencesManager.defaultDownloadDir() }
            FileUtils.openFolder(context, dirPath)
        }

        binding.btnCloseDialog.setOnClickListener { dismiss() }

        binding.btnSaveSettings.setOnClickListener {
            val oldSettings = prefs.getSettings()
            val chosenLang = langOptions[binding.spLanguage.selectedItemPosition].second
            val chosenTheme = themeOptions[binding.spTheme.selectedItemPosition].second
            val updated = AppSettings(
                downloadDir = binding.etDownloadDir.text.toString().trim().ifEmpty { PreferencesManager.defaultDownloadDir() },
                language = chosenLang,
                theme = chosenTheme,
                concurrentDownloads = concurrentCount,
                preferMp4 = binding.cbPreferMp4.isChecked
            )
            prefs.saveSettings(updated)
            onSaved(oldSettings, updated)
            dismiss()
        }
    }

    fun updateSelectedPath(path: String) {
        if (::binding.isInitialized) {
            binding.etDownloadDir.setText(path)
        }
    }
}
