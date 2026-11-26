package com.shawniks.kodikdown.ui

import android.R as AndroidR
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.Uri
import android.os.SystemClock
import android.util.Log
import android.view.HapticFeedbackConstants
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.CompoundButton
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.shawniks.kodikdown.BuildConfig
import com.shawniks.kodikdown.KodikApp
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.databinding.ActivityMainBinding
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.util.FileUtils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal class SettingsTab(
    private val activity: AppCompatActivity,
    private val prefs: PreferencesManager,
    private val currentBinding: () -> ActivityMainBinding,
    private val isResolving: () -> Boolean,
    private val chooseFolder: () -> Unit,
    private val triggerHaptic: (Int) -> Unit,
    private val getColorFromAttr: (Int) -> Int,
) {
    private val binding get() = currentBinding()
    private var bindingSettings = false
    private val settingsClicks = ActionGate(500L)
    var appearanceBusy = false
        private set
    private var languageTransition = false
    private var cacheSizeJob: Job? = null
    private var clearingCache = false

    private fun acceptSettingsClick(): Boolean = !bindingSettings && !appearanceBusy &&
        settingsClicks.accept(SystemClock.elapsedRealtime())

    fun applied() {
        if (bindingSettings) return
        triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
        binding.settingsSaveIndicator.pulse()
    }

    fun transfersLocked(): Boolean =
        isResolving() || DownloadManager.items.value.any { it.isWorking }

    fun updateEnabled() {
        val unlocked = !transfersLocked()
        binding.tvSettingsLocked.visibility = if (unlocked) View.GONE else View.VISIBLE
        listOf(binding.btnSettingsBrowseFolder, binding.btnSettingsResetFolder,
            binding.btnSettingsMinusConcurrent, binding.btnSettingsPlusConcurrent,
            binding.spDefaultQuality, binding.switchPreferMp4, binding.switchWifiOnly,
            binding.btnResetSettings).forEach {
            it.isEnabled = unlocked && !appearanceBusy
            it.alpha = if (it.isEnabled) 1f else 0.45f
        }
        listOf(binding.btnThemeAuto, binding.btnThemeLight, binding.btnThemeDark,
            binding.btnLangAuto, binding.btnLangRu, binding.btnLangEn).forEach {
            it.isEnabled = !appearanceBusy && !isResolving()
        }
    }

    private fun captureAppearance(fade: Boolean, sourceView: View? = null) {
        appearanceBusy = true
        languageTransition = fade
        triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
        val root = binding.rootContainer
        val loc = IntArray(2)
        val origin = IntArray(2)
        root.getLocationInWindow(origin)
        sourceView?.getLocationInWindow(loc)
        try {
            val bitmap = Bitmap.createBitmap(
                (root.width / 2).coerceAtLeast(1), (root.height / 2).coerceAtLeast(1),
                Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            canvas.scale(0.5f, 0.5f)
            root.draw(canvas)
            ThemeRevealHelper.snapshot = bitmap
            ThemeRevealHelper.originX = if (sourceView == null) root.width / 2
                else loc[0] - origin[0] + sourceView.width / 2
            ThemeRevealHelper.originY = if (sourceView == null) root.height / 2
                else loc[1] - origin[1] + sourceView.height / 2
        } catch (e: RuntimeException) {
            Log.w("SettingsTab", "Could not capture appearance", e)
            ThemeRevealHelper.clear()
        }
        updateEnabled()
    }

    private fun finishAppearance() {
        ThemeRevealHelper.clear()
        appearanceBusy = false
        bind()
        binding.settingsSaveIndicator.pulse()
    }

    private fun changeThemeWithReveal(newTheme: String, sourceView: View?) {
        if (isResolving() || prefs.theme == newTheme || !acceptSettingsClick()) return
        captureAppearance(false, sourceView)
        prefs.theme = newTheme
        KodikApp.applyTheme(newTheme)
        // Selecting Auto can keep the effective theme unchanged.
        binding.root.postDelayed({
            if (appearanceBusy && binding.themeOverlay.visibility != View.VISIBLE) finishAppearance()
        }, 500)
        bind()
    }

    private fun changeLanguage(newLang: String) {
        if (isResolving() || prefs.language == newLang || !acceptSettingsClick()) return
        captureAppearance(true)
        prefs.language = newLang
        KodikApp.updateAppLocale(newLang)
        binding.root.postDelayed({
            if (appearanceBusy && binding.themeOverlay.visibility != View.VISIBLE) finishAppearance()
        }, 500)
    }

    fun install() {
        bind()

        binding.btnThemeAuto.setOnClickListener {
            changeThemeWithReveal("auto", it)
        }
        binding.btnThemeLight.setOnClickListener {
            changeThemeWithReveal("light", it)
        }
        binding.btnThemeDark.setOnClickListener {
            changeThemeWithReveal("dark", it)
        }

        binding.btnLangAuto.setOnClickListener { changeLanguage("auto") }
        binding.btnLangRu.setOnClickListener { changeLanguage("ru") }
        binding.btnLangEn.setOnClickListener { changeLanguage("en") }

        binding.btnSettingsBrowseFolder.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (!transfersLocked()) {
                triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
                chooseFolder()
            }
        }

        binding.btnSettingsResetFolder.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transfersLocked()) return@setOnClickListener
            val def = PreferencesManager.defaultDownloadDir()
            prefs.downloadDir = def
            binding.tvSettingsDownloadDir.text = def
            binding.tvFooterPath.text = def
            applied()
        }

        binding.btnSettingsMinusConcurrent.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transfersLocked()) return@setOnClickListener
            if (prefs.concurrentDownloads > 1) {
                prefs.concurrentDownloads--
                binding.tvSettingsConcurrentCount.text = prefs.concurrentDownloads.toString()
                DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
                applied()
            }
        }

        binding.btnSettingsPlusConcurrent.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transfersLocked()) return@setOnClickListener
            if (prefs.concurrentDownloads < 5) {
                prefs.concurrentDownloads++
                binding.tvSettingsConcurrentCount.text = prefs.concurrentDownloads.toString()
                DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
                applied()
            }
        }

        val qualityValues = listOf("ask", "best", "1080", "720", "480", "360")
        val qualityLabels = listOf(
            activity.getString(R.string.quality_ask),
            activity.getString(R.string.quality_best),
            "1080p",
            "720p",
            "480p",
            "360p"
        )
        val qualityAdapter = ArrayAdapter(activity, AndroidR.layout.simple_spinner_dropdown_item, qualityLabels)
        binding.spDefaultQuality.adapter = qualityAdapter
        val curIndex = qualityValues.indexOf(prefs.defaultQuality).coerceAtLeast(0)
        binding.spDefaultQuality.setSelection(curIndex)

        binding.spDefaultQuality.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val chosen = qualityValues[position]
                if (prefs.defaultQuality != chosen) {
                    if (bindingSettings || transfersLocked()) return
                    if (!acceptSettingsClick()) {
                        binding.spDefaultQuality.setSelection(qualityValues.indexOf(prefs.defaultQuality).coerceAtLeast(0))
                        return
                    }
                    prefs.defaultQuality = chosen
                    applied()
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        binding.switchPreferMp4.saveSetting { checked ->
            prefs.preferMp4 = checked
            binding.cbDownloadMp4.isChecked = checked
        }
        binding.switchWifiOnly.saveSetting { prefs.wifiOnly = it }
        binding.switchGroupSeries.saveSetting { prefs.groupSeries = it }
        binding.switchAutoPaste.saveSetting { prefs.autoPaste = it }
        binding.switchSwipeDelete.saveSetting { prefs.swipeToDelete = it }
        binding.switchConfirmSwipeDelete.saveSetting { prefs.confirmSwipeDelete = it }
        binding.switchConfirmCancelDownload.saveSetting { prefs.confirmCancelDownload = it }

        binding.switchHapticFeedback.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) {
                bind()
                return@setOnCheckedChangeListener
            }
            if (isChecked) prefs.hapticFeedback = true
            applied()
            prefs.hapticFeedback = isChecked
        }

        binding.btnSettingsClearCache.setOnClickListener {
            if (clearingCache || !acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            clearingCache = true
            activity.lifecycleScope.launch {
                try {
                    withContext(Dispatchers.IO) {
                        FileUtils.clearCache(activity.cacheDir, activity.codeCacheDir)
                    }
                    updateCacheSizeDisplay()
                    ToastManager.show(binding.toastContainer, activity.getString(R.string.cache_cleared))
                } finally { clearingCache = false }
            }
        }

        binding.btnSettingsClearCompleted.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            DownloadManager.clearFinished()
            ToastManager.show(binding.toastContainer, activity.getString(R.string.completed_downloads_cleared))
        }

        binding.btnSettingsClearAllHistory.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            MaterialAlertDialogBuilder(activity)
                .setTitle(R.string.clear_history)
                .setMessage(R.string.clear_history_confirm)
                .setPositiveButton(R.string.clear_history) { _, _ ->
                    HistoryManager.clear(activity)
                    ToastManager.show(binding.toastContainer, activity.getString(R.string.clear_history))
                }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        binding.btnResetSettings.applyPressEffect()
        binding.btnResetSettings.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transfersLocked() || appearanceBusy) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            MaterialAlertDialogBuilder(activity)
                .setTitle(R.string.reset_defaults)
                .setMessage(R.string.reset_defaults_confirm)
                .setPositiveButton(R.string.reset_defaults) { _, _ ->
                    if (transfersLocked() || appearanceBusy) return@setPositiveButton
                    captureAppearance(true)
                    prefs.resetToDefaults()
                    DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
                    KodikApp.applyTheme(prefs.theme)
                    KodikApp.updateAppLocale(prefs.language)
                    binding.tvFooterPath.text = prefs.downloadDir
                    bind()
                    binding.root.postDelayed({ if (appearanceBusy) finishAppearance() }, 600)
                }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        binding.btnSettingsGithub.applyPressEffect()
        binding.btnSettingsGithub.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            try {
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(activity.getString(R.string.github_url)))
                activity.startActivity(intent)
            } catch (e: Exception) {
                Log.w("SettingsTab", "Cannot open GitHub", e)
            }
        }
    }

    private fun CompoundButton.saveSetting(update: (Boolean) -> Unit) {
        setOnCheckedChangeListener { _, checked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) {
                bind()
                return@setOnCheckedChangeListener
            }
            update(checked)
            applied()
        }
    }

    fun bind() {
        bindingSettings = true
        binding.tvSettingsAppVersion.text = activity.getString(R.string.settings_app_version, BuildConfig.VERSION_NAME)
        val accentColor = getColorFromAttr(R.attr.app_accent)
        val normalColor = getColorFromAttr(R.attr.app_text_muted)

        val curTheme = prefs.theme
        updatePill(binding.btnThemeAuto, curTheme == "auto", accentColor, normalColor)
        updatePill(binding.btnThemeLight, curTheme == "light", accentColor, normalColor)
        updatePill(binding.btnThemeDark, curTheme == "dark", accentColor, normalColor)

        val curLang = prefs.language
        updatePill(binding.btnLangAuto, curLang == "auto", accentColor, normalColor)
        updatePill(binding.btnLangRu, curLang == "ru", accentColor, normalColor)
        updatePill(binding.btnLangEn, curLang == "en", accentColor, normalColor)

        binding.tvSettingsDownloadDir.text = prefs.downloadDir
        binding.tvSettingsConcurrentCount.text = prefs.concurrentDownloads.toString()

        binding.switchPreferMp4.isChecked = prefs.preferMp4
        binding.switchGroupSeries.isChecked = prefs.groupSeries
        binding.switchWifiOnly.isChecked = prefs.wifiOnly
        binding.switchAutoPaste.isChecked = prefs.autoPaste

        binding.switchSwipeDelete.isChecked = prefs.swipeToDelete
        binding.switchConfirmSwipeDelete.isChecked = prefs.confirmSwipeDelete
        binding.switchConfirmCancelDownload.isChecked = prefs.confirmCancelDownload
        binding.switchHapticFeedback.isChecked = prefs.hapticFeedback

        updateCacheSizeDisplay()
        bindingSettings = false
        updateEnabled()
    }

    private fun updatePill(view: TextView, isActive: Boolean, activeColor: Int, normalColor: Int) {
        if (isActive) {
            view.setBackgroundResource(R.drawable.bg_pill_active)
            view.setTextColor(activeColor)
        } else {
            view.setBackgroundResource(R.drawable.bg_pill_inactive)
            view.setTextColor(normalColor)
        }
    }

    private fun updateCacheSizeDisplay() {
        cacheSizeJob?.cancel()
        val label = binding.tvSettingsCacheSize
        cacheSizeJob = activity.lifecycleScope.launch {
            val size = withContext(Dispatchers.IO) { getAppCacheSize() }
            if (label === binding.tvSettingsCacheSize) {
                label.text = activity.getString(R.string.cache_size, FileUtils.formatFileSize(size))
            }
        }
    }

    private fun getAppCacheSize(): Long {
        var size = 0L
        try {
            activity.cacheDir?.walkTopDown()?.filter { it.isFile }?.forEach { size += it.length() }
            activity.codeCacheDir?.walkTopDown()?.filter { it.isFile }?.forEach { size += it.length() }
        } catch (_: Exception) {}
        return size
    }

    fun restoreAppearance() {
        val bitmap = ThemeRevealHelper.snapshot
        if (appearanceBusy && bitmap != null) {
            if (languageTransition) binding.themeOverlay.startFade(bitmap) { finishAppearance() }
            else binding.themeOverlay.startReveal(bitmap,
                ThemeRevealHelper.originX.toFloat(), ThemeRevealHelper.originY.toFloat(),
                duration = 300L) { finishAppearance() }
        } else if (appearanceBusy) finishAppearance()
    }
}
