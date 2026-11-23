package com.shawniks.kodikdown

import android.Manifest
import android.R as AndroidR
import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.util.Log
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.view.animation.OvershootInterpolator
import android.view.inputmethod.EditorInfo
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.addCallback
import androidx.activity.viewModels
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.HistoryItem
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.LibraryManager
import com.shawniks.kodikdown.data.MediaFiles
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.data.ResolvedVideo
import com.shawniks.kodikdown.data.StreamVariant
import com.shawniks.kodikdown.data.Translation
import com.shawniks.kodikdown.databinding.ActivityMainBinding
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.kodik.CatalogClient
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.ui.AnimationExtensions.popBounce
import com.shawniks.kodikdown.ui.CatalogDialog
import com.shawniks.kodikdown.ui.DownloadLookup
import com.shawniks.kodikdown.ui.MediaTabs
import com.shawniks.kodikdown.ui.SettingsTab
import com.shawniks.kodikdown.ui.ToastManager
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.io.IOException
import java.util.ArrayDeque
import java.util.regex.Pattern
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private val lookup: DownloadLookup by viewModels()
    internal var readClipboard: () -> String? = ::readSystemClipboard
    internal var writeClipboard: (String) -> Unit = { link ->
        getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("video_url", link))
    }
    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: PreferencesManager
    private lateinit var settingsTab: SettingsTab
    private lateinit var mediaTabs: MediaTabs
    private lateinit var renderedConfiguration: Configuration

    private var resolveJob: Job? = null
    private var isResolving = false
    private var resolveGeneration = 0
    private var fileChecks: Job? = null
    private var pendingStorageAction: (() -> Unit)? = null



    private var currentTab = 0
    private val tabBackStack = ArrayDeque<Int>()
    private var lastDownloadClickTime = 0L

    private val folderPickerLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri: Uri? ->
            if (uri != null && !settingsTab.transfersLocked()) {
                try {
                    contentResolver.takePersistableUriPermission(
                        uri,
                        Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                    )
                } catch (_: SecurityException) {
                    ToastManager.show(binding.toastContainer, getString(R.string.storage_permission_required), isError = true)
                    return@registerForActivityResult
                }
                val selectedFolder = uri.toString()
                prefs.downloadDir = selectedFolder
                binding.tvFooterPath.text = selectedFolder
                binding.tvSettingsDownloadDir.text = selectedFolder
                settingsTab.applied()
            }
        }

    private val requestNotificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { _ -> }

    private val requestStoragePermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            val action = pendingStorageAction
            pendingStorageAction = null
            if (granted) action?.invoke()
            else
                ToastManager.show(
                    binding.toastContainer,
                    getString(R.string.storage_permission_required),
                    isError = true,
                )
        }

    private fun withStoragePermission(action: () -> Unit) {
        if (
            Build.VERSION.SDK_INT <= Build.VERSION_CODES.P &&
                !prefs.downloadDir.startsWith("content://") &&
                ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.WRITE_EXTERNAL_STORAGE,
                ) != PackageManager.PERMISSION_GRANTED
        ) {
            pendingStorageAction = action
            requestStoragePermissionLauncher.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        } else action()
    }

    override fun recreate() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            overrideActivityTransition(OVERRIDE_TRANSITION_OPEN, R.anim.no_anim, R.anim.no_anim)
            overrideActivityTransition(OVERRIDE_TRANSITION_CLOSE, R.anim.no_anim, R.anim.no_anim)
        } else {
            @Suppress("DEPRECATION")
            overridePendingTransition(R.anim.no_anim, R.anim.no_anim)
        }
        super.recreate()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putInt("saved_tab", currentTab)
        outState.putString("url_input", binding.etUrl.text?.toString())
        outState.putString("file_name", binding.etFileName.text?.toString())
        outState.putBoolean("download_mp4", binding.cbDownloadMp4.isChecked)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = PreferencesManager(this)
        settingsTab = SettingsTab(this, prefs, { binding }, { isResolving },
            { folderPickerLauncher.launch(null) }, ::triggerHaptic, ::getColorFromAttr)
        mediaTabs = MediaTabs(this, prefs, { binding }, ::triggerHaptic,
            settingsTab::updateEnabled, ::requestHistoryRetry, { writeClipboard(it) })

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            overrideActivityTransition(OVERRIDE_TRANSITION_OPEN, R.anim.no_anim, R.anim.no_anim)
            overrideActivityTransition(OVERRIDE_TRANSITION_CLOSE, R.anim.no_anim, R.anim.no_anim)
        } else {
            @Suppress("DEPRECATION")
            overridePendingTransition(R.anim.no_anim, R.anim.no_anim)
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        renderedConfiguration = Configuration(resources.configuration)

        onBackPressedDispatcher.addCallback(this) {
            handleBackPressed()
        }

        requestNotificationPermission()
        HistoryManager.init(this)
        LibraryManager.refresh(this, prefs.downloadDir)

        val savedTab = savedInstanceState?.getInt("saved_tab") ?: 0
        val savedUrl = savedInstanceState?.getString("url_input")

        initViews()
        initTabs(savedTab)
        mediaTabs.install()
        settingsTab.install()

        if (savedInstanceState == null) {
            handleIncomingIntent(intent)
        } else if (!savedUrl.isNullOrEmpty()) {
            binding.etUrl.setText(savedUrl)
            if (savedUrl.trim() == lookup.resolvedUrl) restoreResult(
                savedInstanceState.getString("file_name"), savedInstanceState.getBoolean("download_mp4"),
            )
        }
    }

    override fun onResume() {
        super.onResume()
        LibraryManager.refresh(this, prefs.downloadDir)
        fileChecks?.cancel()
        refreshVisibleFiles()
        if (currentTab == 0 && prefs.autoPaste) {
            checkAutoPaste()
        }
    }

    override fun onPause() {
        if (::binding.isInitialized) binding.settingsSaveIndicator.finish()
        fileChecks?.cancel()
        super.onPause()
    }

    private fun refreshVisibleFiles() {
        fileChecks?.cancel()
        if (currentTab == 3) return
        MediaFiles.requestRefresh()
        // Filesystem paths and SAF providers cannot reliably notify us of external deletions.
        fileChecks = lifecycleScope.launch {
            while (isActive) {
                delay(15_000)
                MediaFiles.refresh(this@MainActivity, force = false)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleBackPressed() {
        if (mediaTabs.isSelectionMode) {
            mediaTabs.exitSelectionMode()
            return
        }

        if (tabBackStack.isNotEmpty()) {
            val previousTab = tabBackStack.removeLast()
            switchTab(previousTab, isBack = true)
            return
        }

        if (currentTab != 0) {
            switchTab(0, isBack = true)
            return
        }

        val hasActive = DownloadManager.items.value.any { !it.isTerminal }
        if (hasActive) {
            MaterialAlertDialogBuilder(this)
                .setMessage(R.string.quit_with_downloads)
                .setPositiveButton(R.string.close) { _, _ -> finish() }
                .setNegativeButton(R.string.cancel, null)
                .show()
        } else {
            finish()
        }
    }

    private fun triggerHaptic(type: Int = HapticFeedbackConstants.LONG_PRESS) {
        if (!prefs.hapticFeedback) return
        binding.root.performHapticFeedback(type)
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
                    PackageManager.PERMISSION_GRANTED
            ) {
                requestNotificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun initViews() {
        window.statusBarColor = getColorFromAttr(R.attr.app_surface)
        window.navigationBarColor = getColorFromAttr(R.attr.app_background)
        val dark = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK ==
            Configuration.UI_MODE_NIGHT_YES
        WindowInsetsControllerCompat(window, binding.root).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
        binding.tvFooterPath.text = prefs.downloadDir

        binding.btnClearUrl.applyPressEffect()
        binding.btnPaste.applyPressEffect()
        binding.btnFind.applyPressEffect()
        binding.btnDownload.applyPressEffect()
        binding.btnResultOpenFolder.applyPressEffect()
        binding.btnFooterOpenFolder.applyPressEffect()
        binding.btnClearFinished.applyPressEffect()

        binding.etUrl.addTextChangedListener(
            object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}

                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    binding.btnClearUrl.visibility =
                        if (s.isNullOrEmpty()) View.GONE else View.VISIBLE
                }

                override fun afterTextChanged(s: Editable?) {}
            }
        )

        binding.btnClearUrl.setOnClickListener {
            binding.etUrl.setText("")
            hideResultCard()
            binding.tvStatus.text = getString(R.string.hint)
        }

        binding.etUrl.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                onFindClicked()
                true
            } else false
        }

        binding.btnPaste.setOnClickListener { handlePaste() }
        binding.btnFind.setOnClickListener { onFindClicked() }

        binding.etFileName.addTextChangedListener(
            object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    if (binding.etFileName.hasFocus()) {
                        lookup.nameEdited = true
                    }
                }
                override fun afterTextChanged(s: Editable?) {}
            }
        )

        binding.btnDownload.setOnClickListener { onDownloadClicked() }
        binding.btnResultOpenFolder.setOnClickListener { openDownloadFolder() }
        binding.btnFooterOpenFolder.setOnClickListener { openDownloadFolder() }
        binding.btnClearFinished.setOnClickListener { DownloadManager.clearFinished() }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (!::binding.isInitialized) return
        val changes = renderedConfiguration.diff(newConfig)
        renderedConfiguration = Configuration(newConfig)
        val appearance = ActivityInfo.CONFIG_LOCALE or ActivityInfo.CONFIG_LAYOUT_DIRECTION or ActivityInfo.CONFIG_UI_MODE
        if (!settingsTab.appearanceBusy && changes and appearance == 0) return
        val url = binding.etUrl.text.toString()
        val name = binding.etFileName.text.toString()
        val mp4 = binding.cbDownloadMp4.isChecked
        val scroll = binding.viewSettings.scrollY
        val downloaderScroll = binding.viewDownloader.scrollY
        mediaTabs.unbind()
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        initViews()
        initTabs(currentTab)
        mediaTabs.install()
        settingsTab.install()
        binding.etUrl.setText(url)
        restoreResult(name, mp4)
        if (isResolving) {
            binding.tvFindText.text = getString(R.string.cancel)
            binding.ivFindIcon.setImageResource(R.drawable.ic_close)
            binding.pbResolving.visibility = View.VISIBLE
            binding.btnDownload.isEnabled = false
        }
        binding.viewSettings.post { binding.viewSettings.scrollTo(0, scroll) }
        binding.viewDownloader.post { binding.viewDownloader.scrollTo(0, downloaderScroll) }
        settingsTab.restoreAppearance()
    }

    private fun restoreResult(name: String?, preferMp4: Boolean) {
        lookup.resolved?.let { video ->
            val quality = lookup.selectedVariant?.quality
            displayResolvedVideo(video)
            if (quality != null) buildQualityPills(video.variants, quality)
            if (name != null) binding.etFileName.setText(name)
        }
        binding.cbDownloadMp4.isChecked = preferMp4
    }

    private fun checkAutoPaste() {
        if (!prefs.autoPaste || isResolving) return
        if (binding.etUrl.text?.isNotEmpty() == true) return
        val text = extractClipboardText() ?: return
        if (text.contains("kodik") || text.contains("iframe")) {
            val url = extractUrlFromText(text)
            binding.etUrl.setText(url)
            binding.etUrl.setSelection(url.length)
            ToastManager.show(binding.toastContainer, getString(R.string.link_copied))
            onFindClicked()
        }
    }

    private fun isWifiConnected(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return true
        val activeNet = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(activeNet) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
    }

    override fun onDestroy() {
        if (::binding.isInitialized) binding.settingsSaveIndicator.finish()
        if (::mediaTabs.isInitialized) mediaTabs.unbind()
        duplicateDialog?.dismiss()
        super.onDestroy()
    }

    private fun initTabs(savedTab: Int = 0) {
        binding.tabDownloader.setOnClickListener { switchTab(0) }
        binding.tabLibrary.setOnClickListener { switchTab(1) }
        binding.tabHistory.setOnClickListener { switchTab(2) }
        binding.tabSettings.setOnClickListener { switchTab(3) }

        binding.tabDownloader.applyPressEffect()
        binding.tabLibrary.applyPressEffect()
        binding.tabHistory.applyPressEffect()
        binding.tabSettings.applyPressEffect()

        switchTab(savedTab, isBack = false)
    }

    private fun switchTab(index: Int, isBack: Boolean = false) {
        if (currentTab == index && isViewInitialized(index)) return

        if (mediaTabs.isSelectionMode) {
            mediaTabs.exitSelectionMode()
        }

        val previousIndex = currentTab
        if (!isBack && previousIndex != index) {
            tabBackStack.addLast(previousIndex)
        }

        if (index != 0) {
            WindowInsetsControllerCompat(window, currentFocus ?: binding.root)
                .hide(WindowInsetsCompat.Type.ime())
        }
        val tabViews = listOf(
            binding.viewDownloader,
            binding.viewLibrary,
            binding.viewHistory,
            binding.viewSettings
        )

        tabViews.forEachIndexed { i, view ->
            view.animate().cancel()
            view.visibility = if (i == index) View.VISIBLE else View.GONE
            view.translationX = 0f
            view.alpha = 1f
        }

        currentTab = index
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) refreshVisibleFiles()
        updateTabUi(index)
        if (index != 0) {
            binding.etUrl.clearFocus()
            binding.etFileName.clearFocus()
        }

        when (index) {
            0 -> if (prefs.autoPaste && !settingsTab.appearanceBusy) checkAutoPaste()
            1 -> LibraryManager.refresh(this, prefs.downloadDir)
            2 -> HistoryManager.init(this)
            3 -> settingsTab.bind()
        }
    }

    private fun isViewInitialized(index: Int): Boolean {
        val tabViews = listOf(
            binding.viewDownloader,
            binding.viewLibrary,
            binding.viewHistory,
            binding.viewSettings
        )
        return tabViews.getOrNull(index)?.visibility == View.VISIBLE
    }

    private fun updateTabUi(activeTab: Int) {
        val accentColor = getColorFromAttr(R.attr.app_accent)
        val mutedColor = getColorFromAttr(R.attr.app_text_muted)

        binding.ivTabDownloader.setColorFilter(if (activeTab == 0) accentColor else mutedColor)
        binding.tvTabDownloader.setTextColor(if (activeTab == 0) accentColor else mutedColor)

        binding.ivTabLibrary.setColorFilter(if (activeTab == 1) accentColor else mutedColor)
        binding.tvTabLibrary.setTextColor(if (activeTab == 1) accentColor else mutedColor)

        binding.ivTabHistory.setColorFilter(if (activeTab == 2) accentColor else mutedColor)
        binding.tvTabHistory.setTextColor(if (activeTab == 2) accentColor else mutedColor)

        binding.ivTabSettings.setColorFilter(if (activeTab == 3) accentColor else mutedColor)
        binding.tvTabSettings.setTextColor(if (activeTab == 3) accentColor else mutedColor)
    }

    private fun requestHistoryRetry(item: HistoryItem) {
        if (isResolving) return
        val safeName = FileUtils.safeFileName(item.fileName)
        if (DownloadManager.isAlreadyActive(item.url, safeName, item.series)) {
            ToastManager.show(binding.toastContainer, getString(R.string.already_downloading))
            return
        }
        confirmExistingDownload(safeName, listOf(item.savedPath to item.contentUri)) {
            retryHistory(item, safeName)
        }
    }

    private fun retryHistory(item: HistoryItem, safeName: String) {
        if (isResolving) return
        if (prefs.wifiOnly && !isWifiConnected()) {
            ToastManager.show(binding.toastContainer, getString(R.string.wifi_only_warning), isError = true)
            return
        }
        val generation = ++resolveGeneration
        resolveJob?.cancel()
        isResolving = true
        settingsTab.updateEnabled()
        binding.btnDownload.isEnabled = false
        binding.tvFindText.setText(R.string.cancel)
        binding.ivFindIcon.setImageResource(R.drawable.ic_close)
        binding.pbResolving.visibility = View.VISIBLE
        binding.tvStatus.setText(R.string.resolving)
        switchTab(0)
        resolveJob = lifecycleScope.launch {
            try {
                val retry = lookup.retry(item)
                if (generation != resolveGeneration) return@launch
                val variant = retry.variant
                val direct = if (item.isMp4) variant.directMp4 else null
                val directory = prefs.downloadDir
                withStoragePermission {
                    if (prefs.wifiOnly && !isWifiConnected()) {
                        ToastManager.show(binding.toastContainer, getString(R.string.wifi_only_warning), isError = true)
                    } else {
                        DownloadManager.enqueueDownload(
                            context = this@MainActivity, title = item.title, fileName = safeName,
                            url = direct ?: variant.url, quality = variant.quality,
                            isMp4 = direct != null || variant.kind == "mp4", downloadDir = directory,
                            translationTitle = retry.translation, hlsUrl = if (direct != null && variant.kind == "hls") variant.url else null,
                            fallbackVariants = retry.variants, sourceInput = retry.source,
                            retryInput = item.retryInput, series = item.series,
                            referer = variant.referer,
                        )
                        ToastManager.show(binding.toastContainer, getString(R.string.starting))
                    }
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                if (generation == resolveGeneration) {
                    ToastManager.show(binding.toastContainer, getString(R.string.network_error, error.message.orEmpty()), isError = true)
                }
            } finally {
                if (generation == resolveGeneration) {
                    isResolving = false
                    settingsTab.updateEnabled()
                    binding.btnDownload.isEnabled = lookup.resolved != null
                    binding.tvFindText.setText(R.string.resolve)
                    binding.ivFindIcon.setImageResource(R.drawable.ic_play)
                    binding.pbResolving.visibility = View.GONE
                    binding.tvStatus.setText(R.string.hint)
                }
            }
        }
    }

    private fun handleIncomingIntent(intent: Intent?) {
        if (intent == null) return
        val text =
            when (intent.action) {
                Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)
                Intent.ACTION_VIEW -> intent.dataString
                else -> null
            }
        if (!text.isNullOrEmpty()) {
            val cleaned = extractUrlFromText(text)
            binding.etUrl.setText(cleaned)
            binding.etUrl.setSelection(cleaned.length)
            onFindClicked()
        }
    }

    private fun extractUrlFromText(raw: String): String {
        val normalized = CatalogClient.normalize(raw)
        if (normalized != raw.trim()) return normalized
        var text = raw.trim()

        // 1. If it's an iframe tag, extract src
        val iframeMatcher =
            Pattern.compile(
                """<iframe[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
                Pattern.CASE_INSENSITIVE,
            )
            .matcher(text)
        if (iframeMatcher.find()) {
            val src = iframeMatcher.group(1)?.trim()
            if (!src.isNullOrEmpty()) {
                text = src
            }
        }

        // 2. Protocol-relative URL "//kodikplayer.com/..."
        if (text.startsWith("//")) {
            text = "https:$text"
        }

        // 3. If there is a full URL inside surrounding text
        val urlMatcher =
            Pattern.compile("""https?://[^\s"'<>]+""", Pattern.CASE_INSENSITIVE).matcher(text)
        if (urlMatcher.find()) {
            text = urlMatcher.group(0) ?: text
        }

        return text.trim()
    }

    private fun extractClipboardText(): String? = readClipboard()?.let(::extractUrlFromText)

    private fun readSystemClipboard(): String? {
        try {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            val clip = clipboard?.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val item = clip.getItemAt(0)
                val text = item.text?.toString() ?: item.uri?.toString()
                if (!text.isNullOrEmpty()) {
                    return text
                }
            }
        } catch (e: Exception) {
            Log.w("MainActivity", "Error extracting clipboard text", e)
        }
        return null
    }

    private fun handlePaste() {
        binding.etUrl.requestFocus()

        val text = extractClipboardText()
        if (!text.isNullOrEmpty()) {
            binding.etUrl.setText(text)
            binding.etUrl.setSelection(text.length)
            onFindClicked()
            return
        }

        val prevText = binding.etUrl.text?.toString().orEmpty()
        binding.etUrl.selectAll()
        val pasted =
            try {
                binding.etUrl.onTextContextMenuItem(AndroidR.id.paste)
            } catch (e: Exception) {
                false
            }

        val afterText = binding.etUrl.text?.toString()?.trim().orEmpty()
        if (pasted && afterText.isNotEmpty() && (afterText != prevText || prevText.isNotEmpty())) {
            val cleaned = extractUrlFromText(afterText)
            if (cleaned != afterText) {
                binding.etUrl.setText(cleaned)
            }
            binding.etUrl.setSelection(binding.etUrl.text?.length ?: 0)
            onFindClicked()
        } else if (afterText.isNotEmpty() && prevText.isEmpty()) {
            val cleaned = extractUrlFromText(afterText)
            if (cleaned != afterText) {
                binding.etUrl.setText(cleaned)
            }
            binding.etUrl.setSelection(binding.etUrl.text?.length ?: 0)
            onFindClicked()
        } else {
            if (binding.etUrl.text?.toString() != prevText) {
                binding.etUrl.setText(prevText)
            }
            binding.etUrl.setSelection(binding.etUrl.text?.length ?: 0)
            ToastManager.show(binding.toastContainer, getString(R.string.paste_empty))
        }
    }

    private fun onFindClicked() {
        if (isResolving) {
            cancelResolving()
            return
        }

        val url = binding.etUrl.text.toString().trim()
        if (url.isEmpty()) {
            ToastManager.show(binding.toastContainer, getString(R.string.link_required))
            return
        }

        startResolving(url)
    }

    private fun startResolving(rawUrl: String, translation: Translation? = null) {
        val generation = ++resolveGeneration
        resolveJob?.cancel()
        isResolving = true
        settingsTab.updateEnabled()
        binding.btnDownload.isEnabled = false
        binding.tvFindText.text = getString(R.string.cancel)
        binding.ivFindIcon.setImageResource(R.drawable.ic_close)
        binding.pbResolving.visibility = View.VISIBLE
        binding.tvStatus.text = getString(R.string.resolving)
        resolveJob =
            lifecycleScope.launch {
                try {
                    val catalog = if (translation == null) lookup.catalog(rawUrl) else null
                    if (catalog != null) {
                        if (catalog.choices.none { it.episodes.isNotEmpty() }) {
                            throw IOException(getString(R.string.catalog_empty))
                        }
                        val cover = lookup.poster(catalog.poster)
                        if (generation != resolveGeneration) return@launch
                        hideResultCard()
                        binding.tvStatus.text = catalog.title
                        val episodeResolver = lookup
                        CatalogDialog(this@MainActivity, catalog, cover, prefs.defaultQuality.toIntOrNull(), prefs.groupSeries) {
                            choice, episodes, quality, grouped ->
                            if (prefs.wifiOnly && !isWifiConnected()) {
                                ToastManager.show(binding.toastContainer, getString(R.string.wifi_only_warning), isError = true)
                            } else withStoragePermission {
                                episodes.forEach { episode ->
                                    val number = episode.number.padStart(2, '0')
                                    val label = getString(R.string.episode_number, number)
                                    val title = if (grouped) label else "$label · ${catalog.title.take(65)}"
                                    val name = listOf(title, choice.voice).filter { it.isNotBlank() }.joinToString(" · ")
                                    DownloadManager.enqueueDownload(
                                        context = this@MainActivity, title = name, fileName = name,
                                        url = episode.url, quality = quality, isMp4 = prefs.preferMp4,
                                        downloadDir = prefs.downloadDir, translationTitle = choice.voice,
                                        sourceInput = CatalogClient.normalize(catalog.url),
                                        retryInput = episode.url, series = catalog.title.takeIf { grouped },
                                        prepare = { episodeResolver.resolve(episode.url) },
                                    )
                                }
                            }
                        }.show()
                        return@launch
                    }
                    val resolved = lookup.resolve(rawUrl, translation)
                    if (generation == resolveGeneration) {
                        if (lookup.resolvedUrl != rawUrl) lookup.nameEdited = false
                        lookup.resolvedUrl = rawUrl
                        lookup.resolved = resolved
                        displayResolvedVideo(resolved)
                        binding.tvStatus.text = getString(R.string.hint)
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (generation == resolveGeneration) {
                        hideResultCard()
                        val msg = e.message ?: getString(R.string.network_error, "Unknown error")
                        binding.tvStatus.text = msg
                        ToastManager.show(binding.toastContainer, msg, isError = true)
                    }
                } finally {
                    if (generation == resolveGeneration) {
                        isResolving = false
                        settingsTab.updateEnabled()
                        binding.btnDownload.isEnabled = lookup.resolved != null
                        binding.tvFindText.text = getString(R.string.resolve)
                        binding.ivFindIcon.setImageResource(R.drawable.ic_play)
                        binding.pbResolving.visibility = View.GONE
                    }
                }
            }
    }

    private fun cancelResolving() {
        resolveGeneration++
        resolveJob?.cancel()
        isResolving = false
        settingsTab.updateEnabled()
        lookup.resolved?.let { populateTranslations(it) }
        binding.btnDownload.isEnabled = lookup.resolved != null
        binding.tvFindText.text = getString(R.string.resolve)
        binding.ivFindIcon.setImageResource(R.drawable.ic_play)
        binding.pbResolving.visibility = View.GONE
        binding.tvStatus.text = getString(R.string.hint)
    }

    private fun displayResolvedVideo(video: ResolvedVideo) {
        binding.tvResultTitle.text = video.title

        if (video.warnings.contains("proxy")) {
            binding.tvWarning.visibility = View.VISIBLE
        } else {
            binding.tvWarning.visibility = View.GONE
        }

        if (!lookup.nameEdited) {
            binding.etFileName.setText(FileUtils.safeFileName(video.title))
        }

        populateTranslations(video)

        buildQualityPills(video.variants, video.defaultQuality)
        binding.cbDownloadMp4.isChecked = prefs.preferMp4

        if (binding.cardResult.visibility != View.VISIBLE) {
            binding.cardResult.alpha = 0f
            binding.cardResult.visibility = View.VISIBLE
            binding.cardResult.translationY = -dpToPx(16).toFloat()
            binding.cardResult.scaleX = 0.95f
            binding.cardResult.scaleY = 0.95f
            binding.cardResult
                .animate()
                .alpha(1f)
                .translationY(0f)
                .scaleX(1.0f)
                .scaleY(1.0f)
                .setDuration(350)
                .setInterpolator(OvershootInterpolator(1.3f))
                .setListener(null)
                .start()
        }
    }

    private fun populateTranslations(video: ResolvedVideo) {
        binding.spTranslation.onItemSelectedListener = null
        lookup.selectedTranslation = video.translation ?: video.translations.firstOrNull()
        if (video.translations.isNotEmpty()) {
            binding.rowTranslation.visibility = View.VISIBLE
            val titles = video.translations.map { it.title }
            val adapter = ArrayAdapter(this, AndroidR.layout.simple_spinner_dropdown_item, titles)
            binding.spTranslation.adapter = adapter

            val targetTranslation = video.translation
            val currentIndex =
                if (targetTranslation != null) {
                    video.translations
                        .indexOfFirst {
                            it.mediaId == targetTranslation.mediaId &&
                                it.contentHash == targetTranslation.contentHash
                        }
                        .coerceAtLeast(0)
                } else 0
            binding.spTranslation.setSelection(currentIndex)

            binding.spTranslation.onItemSelectedListener =
                object : AdapterView.OnItemSelectedListener {
                    override fun onItemSelected(
                        parent: AdapterView<*>?,
                        view: View?,
                        pos: Int,
                        id: Long,
                    ) {
                        val picked = video.translations[pos]
                        if (lookup.resolved === video && picked != lookup.selectedTranslation) {
                            startResolving(lookup.resolvedUrl, picked)
                        }
                    }

                    override fun onNothingSelected(parent: AdapterView<*>?) {}
                }
        } else {
            binding.rowTranslation.visibility = View.GONE
        }
    }

    private fun buildQualityPills(variants: List<StreamVariant>, defaultQuality: Int?) {
        binding.layoutQualityPills.removeAllViews()
        if (variants.isEmpty()) return

        var activeVariant = variants.first()
        val prefQual = prefs.defaultQuality
        if (prefQual != "ask") {
            val targetQual = prefQual.toIntOrNull()
            if (targetQual != null) {
                val matched = variants.firstOrNull { it.quality == targetQual }
                if (matched != null) activeVariant = matched
            }
        } else if (defaultQuality != null) {
            val matched = variants.firstOrNull { it.quality == defaultQuality }
            if (matched != null) activeVariant = matched
        }
        lookup.selectedVariant = activeVariant

        for ((index, variant) in variants.withIndex()) {
            val pill =
                TextView(this).apply {
                    val isBest = variant == variants.first()
                    text = when {
                        variant.quality <= 0 -> getString(R.string.quality_original)
                        isBest -> "${variant.quality}p • ${getString(R.string.best_badge)}"
                        else -> "${variant.quality}p"
                    }
                    textSize = 12f
                    gravity = Gravity.CENTER
                    setPadding(dpToPx(12), dpToPx(6), dpToPx(12), dpToPx(6))
                    val params =
                        LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.WRAP_CONTENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT,
                        )
                        .apply { marginEnd = dpToPx(6) }
                    layoutParams = params

                    updatePillStyle(this, variant == activeVariant)
                    applyPressEffect()

                    alpha = 0f
                    scaleX = 0.8f
                    scaleY = 0.8f
                    animate()
                        .alpha(1f)
                        .scaleX(1f)
                        .scaleY(1f)
                        .setStartDelay((index * 35).toLong())
                        .setDuration(240)
                        .setInterpolator(OvershootInterpolator(2.2f))
                        .start()

                    setOnClickListener {
                        popBounce()
                        lookup.selectedVariant = variant
                        for (i in 0 until binding.layoutQualityPills.childCount) {
                            val child = binding.layoutQualityPills.getChildAt(i) as TextView
                            val childVariant = variants[i]
                            updatePillStyle(child, childVariant == variant)
                        }
                    }
                }
            binding.layoutQualityPills.addView(pill)
        }
    }

    private fun updatePillStyle(view: TextView, isActive: Boolean) {
        if (isActive) {
            view.setBackgroundResource(R.drawable.bg_pill_active)
            view.setTextColor(getColorFromAttr(R.attr.app_accent))
        } else {
            view.setBackgroundResource(R.drawable.bg_pill_inactive)
            view.setTextColor(getColorFromAttr(R.attr.app_text))
        }
    }

    private fun onDownloadClicked() {
        if (isResolving) return
        val now = System.currentTimeMillis()
        if (now - lastDownloadClickTime < 800) return
        lastDownloadClickTime = now

        if (prefs.wifiOnly && !isWifiConnected()) {
            ToastManager.show(
                binding.toastContainer,
                getString(R.string.wifi_only_warning),
                isError = true
            )
            return
        }

        val variant = lookup.selectedVariant ?: lookup.resolved?.best ?: return
        val rawName = binding.etFileName.text.toString().trim()
        val safeName = FileUtils.safeFileName(rawName.ifEmpty { lookup.resolved?.title ?: "video" })
        val preferMp4 = binding.cbDownloadMp4.isChecked

        val finalUrl =
            if (preferMp4 && variant.directMp4 != null) {
                variant.directMp4
            } else {
                variant.url
            }
        val isMp4 = variant.kind == "mp4" || (preferMp4 && variant.directMp4 != null)

        if (DownloadManager.isAlreadyActive(finalUrl, safeName)) {
            ToastManager.show(binding.toastContainer, getString(R.string.already_downloading))
            return
        }

        confirmExistingDownload(safeName) {
            startDownloadExecution(variant, safeName, finalUrl, isMp4)
        }
    }

    private var duplicateCheckJob: Job? = null
    private var duplicateDialog: AlertDialog? = null

    private fun confirmExistingDownload(
        safeName: String,
        references: List<Pair<String?, String?>> = emptyList(),
        proceed: () -> Unit,
    ) {
        if (duplicateCheckJob?.isActive == true || duplicateDialog?.isShowing == true) return
        val library = LibraryManager.findExisting(safeName)
        val history = HistoryManager.items.value.filter {
            it.status == DownloadStatus.FINISHED &&
                FileUtils.safeFileName(it.fileName).equals(safeName, ignoreCase = true)
        }
        val directory = prefs.downloadDir
        val candidates = buildList<Pair<String?, String?>> {
            addAll(references)
            library?.let { add(it.filePath to it.contentUri) }
            addAll(history.map { it.savedPath to it.contentUri })
            if (!directory.startsWith("content://")) add(File(directory, "$safeName.mp4").absolutePath to null)
        }
        duplicateCheckJob = lifecycleScope.launch {
            val existing = withContext(Dispatchers.IO) {
                candidates.distinct().firstOrNull { (path, uri) ->
                    MediaFiles.exists(this@MainActivity, path, uri)
                }
            }
            if (existing == null) {
                proceed()
                return@launch
            }
            duplicateDialog = MaterialAlertDialogBuilder(this@MainActivity)
                .setTitle(R.string.already_downloaded_title)
                .setMessage(getString(R.string.already_downloaded_message, safeName))
                .setPositiveButton(R.string.play) { _, _ ->
                    (existing.second ?: existing.first)?.let { FileUtils.openFile(this@MainActivity, it) }
                }
                .setNegativeButton(R.string.download_again) { _, _ -> proceed() }
                .setNeutralButton(R.string.cancel, null)
                .setOnDismissListener { duplicateDialog = null }
                .show()
        }
    }

    private fun startDownloadExecution(
        variant: StreamVariant,
        safeName: String,
        finalUrl: String,
        isMp4: Boolean,
    ) {
        if (isResolving) return
        val video = lookup.resolved ?: return
        if (variant !in video.variants) return
        val translationTitle = lookup.selectedTranslation?.title
        val downloadDir = prefs.downloadDir
        val sourceInput = CatalogClient.normalize(lookup.resolvedUrl.orEmpty())
        withStoragePermission {
            DownloadManager.enqueueDownload(
                context = this,
                title = video.title,
                fileName = safeName,
                url = finalUrl,
                quality = variant.quality,
                isMp4 = isMp4,
                downloadDir = downloadDir,
                translationTitle = translationTitle,
                hlsUrl = variant.url,
                fallbackVariants = video.variants,
                sourceInput = sourceInput,
                referer = variant.referer,
            )
        }

        ToastManager.show(binding.toastContainer, getString(R.string.starting))
    }

    private fun hideResultCard() {
        if (binding.cardResult.visibility == View.VISIBLE) {
            binding.cardResult
                .animate()
                .alpha(0f)
                .translationY(-dpToPx(10).toFloat())
                .setDuration(200)
                .setListener(
                    object : AnimatorListenerAdapter() {
                        override fun onAnimationEnd(animation: Animator) {
                            binding.cardResult.visibility = View.GONE
                        }
                    }
                )
                .start()
        }
        lookup.resolved = null
        lookup.selectedVariant = null
        lookup.nameEdited = false
    }

    private fun openDownloadFolder() {
        FileUtils.openFolder(this, prefs.downloadDir)
    }

    private fun dpToPx(dp: Int): Int {
        return (dp * resources.displayMetrics.density).toInt()
    }

    private fun getColorFromAttr(attrRes: Int): Int {
        val typedArray = obtainStyledAttributes(intArrayOf(attrRes))
        val color = typedArray.getColor(0, 0)
        typedArray.recycle()
        return color
    }
}
