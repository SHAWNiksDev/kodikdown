package com.shawniks.kodikdown

import android.Manifest
import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
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
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.SimpleItemAnimator
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.shawniks.kodikdown.data.HistoryItem
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.LibraryItem
import com.shawniks.kodikdown.data.LibraryManager
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.data.ResolvedVideo
import com.shawniks.kodikdown.data.StreamVariant
import com.shawniks.kodikdown.data.Translation
import com.shawniks.kodikdown.databinding.ActivityMainBinding
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.kodik.KodikClient
import com.shawniks.kodikdown.ui.AnimationExtensions.applyPressEffect
import com.shawniks.kodikdown.ui.AnimationExtensions.popBounce
import com.shawniks.kodikdown.ui.DownloadAdapter
import com.shawniks.kodikdown.ui.HistoryAdapter
import com.shawniks.kodikdown.ui.LibraryAdapter
import com.shawniks.kodikdown.ui.SwipeToDeleteCallback
import com.shawniks.kodikdown.ui.ThemeRevealHelper
import com.shawniks.kodikdown.ui.ToastManager
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.util.ArrayDeque
import java.util.regex.Pattern
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: PreferencesManager
    private val client = KodikClient()

    private var resolveJob: Job? = null
    private var isResolving = false
    private var resolveGeneration = 0
    private val uiCollectors = mutableListOf<Job>()
    private var bindingSettings = false
    private val settingsClicks = com.shawniks.kodikdown.ui.ActionGate(500L)
    private var appearanceBusy = false
    private var languageTransition = false
    private var fileChecks: Job? = null
    private var cacheSizeJob: Job? = null
    private var clearingCache = false
    private val fileObserver = object : android.database.ContentObserver(android.os.Handler(android.os.Looper.getMainLooper())) {
        override fun onChange(selfChange: Boolean) { com.shawniks.kodikdown.data.MediaFiles.requestRefresh() }
    }
    private var pendingStorageAction: (() -> Unit)? = null

    private var currentResolved: ResolvedVideo? = null
    private var resolvedUrl = ""
    private var selectedVariant: StreamVariant? = null
    private var selectedTranslation: Translation? = null
    private var nameManuallyEdited = false

    private lateinit var downloadAdapter: DownloadAdapter
    private lateinit var libraryAdapter: LibraryAdapter
    private lateinit var historyAdapter: HistoryAdapter

    private var currentTab = 0
    private val tabBackStack = ArrayDeque<Int>()
    private var lastDownloadClickTime = 0L

    // Selection mode state
    private enum class SelectionType { NONE, DOWNLOADS, LIBRARY, HISTORY }
    private var selectionType = SelectionType.NONE
    private var isSelectionMode = false

    private val folderPickerLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri: Uri? ->
            if (uri != null && !transferSettingsLocked()) {
                contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                )
                val selectedFolder = uri.toString()
                prefs.downloadDir = selectedFolder
                binding.tvFooterPath.text = selectedFolder
                binding.tvSettingsDownloadDir.text = selectedFolder
                settingsApplied()
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
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = PreferencesManager(this)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            overrideActivityTransition(OVERRIDE_TRANSITION_OPEN, R.anim.no_anim, R.anim.no_anim)
            overrideActivityTransition(OVERRIDE_TRANSITION_CLOSE, R.anim.no_anim, R.anim.no_anim)
        } else {
            @Suppress("DEPRECATION")
            overridePendingTransition(R.anim.no_anim, R.anim.no_anim)
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Predictive back / Back gesture navigation
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
        initDownloadsList()
        initLibrary()
        initHistory()
        initSettings()
        initSelectionBar()

        if (!savedUrl.isNullOrEmpty()) {
            binding.etUrl.setText(savedUrl)
        }

        handleIncomingIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        LibraryManager.refresh(this, prefs.downloadDir)
        fileChecks?.cancel()
        fileChecks = lifecycleScope.launch {
            while (kotlinx.coroutines.currentCoroutineContext().isActive) {
                com.shawniks.kodikdown.data.MediaFiles.refresh(this@MainActivity, force = false)
                kotlinx.coroutines.delay(3000)
            }
        }
        contentResolver.registerContentObserver(android.net.Uri.parse("content://media"), true, fileObserver)
        if (currentTab == 0 && prefs.autoPaste) {
            checkAutoPaste()
        }
    }

    override fun onPause() {
        binding.settingsSaveIndicator.finish()
        fileChecks?.cancel()
        contentResolver.unregisterContentObserver(fileObserver)
        super.onPause()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleBackPressed() {
        if (isSelectionMode) {
            exitSelectionMode()
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

        // Apply interactive micro-interaction press effects
        binding.btnClearUrl.applyPressEffect()
        binding.btnPaste.applyPressEffect()
        binding.btnFind.applyPressEffect()
        binding.btnDownload.applyPressEffect()
        binding.btnResultOpenFolder.applyPressEffect()
        binding.btnFooterOpenFolder.applyPressEffect()
        binding.btnClearFinished.applyPressEffect()

        // URL input text watcher
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
                        nameManuallyEdited = true
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

    private fun acceptSettingsClick(): Boolean = !bindingSettings && !appearanceBusy &&
        settingsClicks.accept(android.os.SystemClock.elapsedRealtime())

    private fun settingsApplied() {
        if (bindingSettings) return
        triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
        binding.settingsSaveIndicator.pulse()
    }

    private fun transferSettingsLocked(): Boolean =
        isResolving || DownloadManager.items.value.any { !it.isTerminal }

    private fun updateSettingsAvailability() {
        val unlocked = !transferSettingsLocked()
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
            it.isEnabled = !appearanceBusy && !isResolving
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
            Log.w("MainActivity", "Could not capture appearance", e)
            ThemeRevealHelper.clear()
        }
        updateSettingsAvailability()
    }

    private fun finishAppearance() {
        ThemeRevealHelper.clear()
        appearanceBusy = false
        bindSettingsUi()
        binding.settingsSaveIndicator.pulse()
    }

    private fun changeThemeWithReveal(newTheme: String, sourceView: View?) {
        if (isResolving || prefs.theme == newTheme || !acceptSettingsClick()) return
        captureAppearance(false, sourceView)
        prefs.theme = newTheme
        KodikApp.applyTheme(newTheme)
        // Selecting Auto can keep the effective theme unchanged.
        binding.root.postDelayed({
            if (appearanceBusy && binding.themeOverlay.visibility != View.VISIBLE) finishAppearance()
        }, 500)
        bindSettingsUi()
    }

    private fun changeLanguage(newLang: String) {
        if (isResolving || prefs.language == newLang || !acceptSettingsClick()) return
        captureAppearance(true)
        prefs.language = newLang
        KodikApp.updateAppLocale(newLang)
        binding.root.postDelayed({
            if (appearanceBusy && binding.themeOverlay.visibility != View.VISIBLE) finishAppearance()
        }, 500)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (!::binding.isInitialized) return
        val url = binding.etUrl.text.toString()
        val name = binding.etFileName.text.toString()
        val edited = nameManuallyEdited
        val mp4 = binding.cbDownloadMp4.isChecked
        val quality = selectedVariant?.quality
        val scroll = binding.viewSettings.scrollY
        val downloaderScroll = binding.viewDownloader.scrollY
        uiCollectors.forEach { it.cancel() }
        uiCollectors.clear()
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        binding.etUrl.setText(url)
        initViews()
        initTabs(currentTab)
        initDownloadsList()
        initLibrary()
        initHistory()
        initSettings()
        initSelectionBar()
        isSelectionMode = false
        selectionType = SelectionType.NONE
        binding.etUrl.setText(url)
        currentResolved?.let {
            displayResolvedVideo(it)
            if (quality != null) buildQualityPills(it.variants, quality)
            binding.etFileName.setText(name)
        }
        binding.cbDownloadMp4.isChecked = mp4
        if (isResolving) {
            binding.tvFindText.text = getString(R.string.cancel)
            binding.ivFindIcon.setImageResource(R.drawable.ic_close)
            binding.pbResolving.visibility = View.VISIBLE
            binding.btnDownload.isEnabled = false
        }
        nameManuallyEdited = edited
        binding.viewSettings.post { binding.viewSettings.scrollTo(0, scroll) }
        binding.viewDownloader.post { binding.viewDownloader.scrollTo(0, downloaderScroll) }
        val bitmap = ThemeRevealHelper.snapshot
        if (appearanceBusy && bitmap != null) {
            if (languageTransition) binding.themeOverlay.startFade(bitmap) { finishAppearance() }
            else binding.themeOverlay.startReveal(bitmap,
                ThemeRevealHelper.originX.toFloat(), ThemeRevealHelper.originY.toFloat(),
                duration = 300L) { finishAppearance() }
        } else if (appearanceBusy) finishAppearance()
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

    private var cancelDownloadDialog: androidx.appcompat.app.AlertDialog? = null
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
        cancelDownloadDialog = MaterialAlertDialogBuilder(this)
            .setTitle(R.string.confirm_cancel_title)
            .setMessage(getString(R.string.confirm_cancel_message, item.title))
            .setPositiveButton(R.string.stop_download) { _, _ -> DownloadManager.cancelDownload(id) }
            .setNegativeButton(R.string.keep_downloading, null)
            .setOnDismissListener {
                cancelDownloadDialog = null
                cancelDownloadDialogId = null
            }
            .show()
    }

    override fun onDestroy() {
        binding.settingsSaveIndicator.finish()
        cancelDownloadDialog?.dismiss()
        super.onDestroy()
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
                        FileUtils.openFile(this, pathOrUri)
                    }
                },
                onShareClicked = { item ->
                    val pathOrUri = item.contentUri ?: item.savedPath
                    if (!pathOrUri.isNullOrEmpty()) {
                        FileUtils.shareFile(this, pathOrUri)
                    }
                },
            )

        binding.rvDownloads.apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = downloadAdapter
            (itemAnimator as? SimpleItemAnimator)?.supportsChangeAnimations = false
        }

        ItemTouchHelper(SwipeToDeleteCallback(this, canSwipe = { position ->
            prefs.swipeToDelete && !isSelectionMode &&
                downloadAdapter.currentList.getOrNull(position)?.isTerminal == true
        }) { position, _ ->
            val item = downloadAdapter.currentList.getOrNull(position) ?: return@SwipeToDeleteCallback
            val reset = { downloadAdapter.notifyDataSetChanged() }
            if (!prefs.swipeToDelete || isSelectionMode || !item.isTerminal) {
                reset()
                return@SwipeToDeleteCallback
            }
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            if (!item.isTerminal || prefs.confirmSwipeDelete) {
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.delete)
                    .setMessage(if (item.isTerminal) getString(R.string.remove_download_confirm)
                        else getString(R.string.cancel_download_confirm))
                    .setPositiveButton(R.string.delete) { _, _ -> DownloadManager.removeDownload(item.id) }
                    .setNegativeButton(R.string.cancel) { _, _ -> reset() }
                    .setOnCancelListener { reset() }
                    .show()
            } else DownloadManager.removeDownload(item.id)
        }).attachToRecyclerView(binding.rvDownloads)

        uiCollectors += lifecycleScope.launch {
            DownloadManager.items.collect { items ->
                downloadAdapter.submitList(items)
                cancelDownloadDialogId?.let { id ->
                    if (!DownloadManager.isActive(id) || DownloadManager.isAssembling(id)) cancelDownloadDialog?.dismiss()
                }
                updateSettingsAvailability()
                if (items.isEmpty()) {
                    binding.tvDownloadsEmpty.visibility = View.VISIBLE
                    binding.rvDownloads.visibility = View.GONE
                } else {
                    binding.tvDownloadsEmpty.visibility = View.GONE
                    binding.rvDownloads.visibility = View.VISIBLE
                }
            }
        }
        uiCollectors += lifecycleScope.launch {
            com.shawniks.kodikdown.data.MediaFiles.availability.collect {
                downloadAdapter.notifyDataSetChanged()
                if (::historyAdapter.isInitialized) historyAdapter.notifyDataSetChanged()
            }
        }
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

        if (isSelectionMode) {
            exitSelectionMode()
        }

        val previousIndex = currentTab
        if (!isBack && previousIndex != index) {
            tabBackStack.addLast(previousIndex)
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
        updateTabUi(index)
        if (index != 0) {
            WindowInsetsControllerCompat(window, binding.root).hide(androidx.core.view.WindowInsetsCompat.Type.ime())
            binding.etUrl.clearFocus()
            binding.etFileName.clearFocus()
        }

        when (index) {
            0 -> if (prefs.autoPaste && !appearanceBusy) checkAutoPaste()
            1 -> LibraryManager.refresh(this, prefs.downloadDir)
            2 -> HistoryManager.init(this)
            3 -> bindSettingsUi()
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

    private fun initLibrary() {
        libraryAdapter =
            LibraryAdapter(
                onPlayClicked = { item ->
                    val uriOrPath = item.contentUri ?: item.filePath
                    if (!uriOrPath.isNullOrEmpty()) {
                        FileUtils.openFile(this, uriOrPath)
                    }
                },
                onShareClicked = { item ->
                    val uriOrPath = item.contentUri ?: item.filePath
                    if (!uriOrPath.isNullOrEmpty()) {
                        FileUtils.shareFile(this, uriOrPath)
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
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = libraryAdapter
        }

        // Swipe-to-delete for Library
        val librarySwipeHelper = ItemTouchHelper(SwipeToDeleteCallback(this) { position, _ ->
            if (!prefs.swipeToDelete) {
                libraryAdapter.notifyItemChanged(position)
                return@SwipeToDeleteCallback
            }
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            val item = libraryAdapter.currentList.getOrNull(position) ?: return@SwipeToDeleteCallback
            if (prefs.confirmSwipeDelete) {
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.delete)
                    .setMessage(getString(R.string.delete_file_confirm, item.title))
                    .setPositiveButton(R.string.delete) { _, _ ->
                        lifecycleScope.launch {
                            LibraryManager.deleteItem(this@MainActivity, item)
                            ToastManager.show(binding.toastContainer, getString(R.string.file_deleted))
                        }
                    }
                    .setNegativeButton(R.string.cancel) { _, _ ->
                        libraryAdapter.notifyItemChanged(position)
                    }
                    .setOnCancelListener {
                        libraryAdapter.notifyItemChanged(position)
                    }
                    .show()
            } else {
                lifecycleScope.launch {
                    LibraryManager.deleteItem(this@MainActivity, item)
                    ToastManager.show(binding.toastContainer, getString(R.string.file_deleted))
                }
            }
        })
        librarySwipeHelper.attachToRecyclerView(binding.rvLibrary)

        binding.btnLibraryRefresh.applyPressEffect()
        binding.btnLibraryRefresh.setOnClickListener {
            binding.btnLibraryRefresh.animate().rotationBy(360f).setDuration(400).start()
            LibraryManager.refresh(this, prefs.downloadDir)
        }

        binding.btnLibraryOpenFolder.applyPressEffect()
        binding.btnLibraryOpenFolder.setOnClickListener {
            FileUtils.openFolder(this, prefs.downloadDir)
        }

        uiCollectors += lifecycleScope.launch {
            LibraryManager.items.collect { list ->
                libraryAdapter.submitList(list)
                if (list.isEmpty()) {
                    binding.llLibraryEmpty.visibility = View.VISIBLE
                    binding.rvLibrary.visibility = View.GONE
                    binding.tvLibraryCount.text = getString(R.string.video_count, 0)
                } else {
                    binding.llLibraryEmpty.visibility = View.GONE
                    binding.rvLibrary.visibility = View.VISIBLE
                    val totalBytes = list.sumOf { it.fileSizeBytes }
                    val sizeStr = FileUtils.formatFileSize(totalBytes)
                    binding.tvLibraryCount.text =
                        "${getString(R.string.video_count, list.size)} • $sizeStr"
                }
            }
        }
    }

    private fun confirmDeleteLibraryItem(item: LibraryItem) {
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.delete)
            .setMessage(getString(R.string.delete_file_confirm, item.title))
            .setPositiveButton(R.string.delete) { _, _ ->
                lifecycleScope.launch {
                    val deleted = LibraryManager.deleteItem(this@MainActivity, item)
                    if (deleted) {
                        ToastManager.show(
                            binding.toastContainer,
                            getString(R.string.file_deleted),
                        )
                    }
                }
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun initHistory() {
        historyAdapter =
            HistoryAdapter(
                onRedownloadClicked = { item ->
                    if (isResolving) return@HistoryAdapter
                    val safeName = FileUtils.safeFileName(item.fileName)
                    if (!DownloadManager.isAlreadyActive(item.url, safeName)) {
                        confirmExistingDownload(safeName, listOf(item.savedPath to item.contentUri)) {
                            retryHistory(item, safeName)
                        }
                    } else ToastManager.show(binding.toastContainer, getString(R.string.already_downloading))
                },
                onPlayClicked = { item ->
                    val uriOrPath = item.contentUri ?: item.savedPath
                    if (!uriOrPath.isNullOrEmpty()) {
                        FileUtils.openFile(this, uriOrPath)
                    } else {
                        FileUtils.openFolder(this, prefs.downloadDir)
                    }
                },
                onCopyClicked = { item ->
                    val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                    val source = com.shawniks.kodikdown.data.HistoryLinks.copySource(item)
                    if (source == null) {
                        ToastManager.show(binding.toastContainer, getString(R.string.original_link_missing))
                        return@HistoryAdapter
                    }
                    val clip = ClipData.newPlainText("video_url", source)
                    clipboard?.setPrimaryClip(clip)
                    ToastManager.show(binding.toastContainer, getString(R.string.link_copied))
                },
                onDeleteClicked = { item -> HistoryManager.remove(this, item.id) },
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
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = historyAdapter
        }

        // Swipe-to-delete for History
        val historySwipeHelper = ItemTouchHelper(SwipeToDeleteCallback(this, canSwipe = { position ->
            prefs.swipeToDelete && !isSelectionMode &&
                historyAdapter.currentList.getOrNull(position)?.let { !DownloadManager.isActive(it.id) } == true
        }) { position, _ ->
            if (!prefs.swipeToDelete) {
                historyAdapter.notifyItemChanged(position)
                return@SwipeToDeleteCallback
            }
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            val item = historyAdapter.currentList.getOrNull(position) ?: return@SwipeToDeleteCallback
            if (prefs.confirmSwipeDelete) {
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.delete)
                    .setMessage(getString(R.string.delete_file_confirm, item.title))
                    .setPositiveButton(R.string.delete) { _, _ ->
                        HistoryManager.remove(this, item.id)
                        ToastManager.show(binding.toastContainer, getString(R.string.item_deleted))
                    }
                    .setNegativeButton(R.string.cancel) { _, _ ->
                        historyAdapter.notifyItemChanged(position)
                    }
                    .setOnCancelListener {
                        historyAdapter.notifyItemChanged(position)
                    }
                    .show()
            } else {
                HistoryManager.remove(this, item.id)
                ToastManager.show(binding.toastContainer, getString(R.string.item_deleted))
            }
        })
        historySwipeHelper.attachToRecyclerView(binding.rvHistory)

        binding.btnHistoryClearAll.applyPressEffect()
        binding.btnHistoryClearAll.setOnClickListener {
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.clear_history)
                .setMessage(R.string.clear_history_confirm)
                .setPositiveButton(R.string.clear_history) { _, _ -> HistoryManager.clear(this) }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        uiCollectors += lifecycleScope.launch {
            HistoryManager.items.collect { list ->
                historyAdapter.submitList(list)
                if (list.isEmpty()) {
                    binding.llHistoryEmpty.visibility = View.VISIBLE
                    binding.rvHistory.visibility = View.GONE
                    binding.tvHistoryCount.text = ""
                } else {
                    binding.llHistoryEmpty.visibility = View.GONE
                    binding.rvHistory.visibility = View.VISIBLE
                    binding.tvHistoryCount.text = getString(R.string.video_count, list.size)
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

            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.delete)
                .setMessage(if (selectionType == SelectionType.DOWNLOADS)
                    getString(R.string.remove_downloads_confirm, count)
                    else getString(R.string.delete_selected_confirm, count))
                .setPositiveButton(R.string.delete) { _, _ ->
                    if (selectionType == SelectionType.DOWNLOADS) {
                        downloadAdapter.selectedIds.toSet().forEach { DownloadManager.removeDownload(it) }
                    } else if (selectionType == SelectionType.LIBRARY) {
                        val idsToDelete = libraryAdapter.selectedIds.toSet()
                        lifecycleScope.launch {
                            val itemsToDelete = libraryAdapter.currentList.filter { it.id in idsToDelete }
                            for (item in itemsToDelete) {
                                LibraryManager.deleteItem(this@MainActivity, item)
                            }
                            ToastManager.show(
                                binding.toastContainer,
                                getString(R.string.items_deleted, idsToDelete.size)
                            )
                        }
                    } else if (selectionType == SelectionType.HISTORY) {
                        val idsToDelete = historyAdapter.selectedIds.toSet()
                        for (id in idsToDelete) {
                            HistoryManager.remove(this, id)
                        }
                        ToastManager.show(
                            binding.toastContainer,
                            getString(R.string.items_deleted, idsToDelete.size)
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
                        val uri = androidx.core.content.FileProvider.getUriForFile(
                            this,
                            "${packageName}.fileprovider",
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
                startActivity(Intent.createChooser(shareIntent, getString(R.string.share_file)))
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
            downloadAdapter.notifyDataSetChanged()
            updateSelectionCount(1)
        } else if (type == SelectionType.LIBRARY) {
            binding.btnSelectionShare.visibility = View.VISIBLE
            libraryAdapter.isSelectionMode = true
            libraryAdapter.selectedIds.clear()
            libraryAdapter.selectedIds.add(initialId)
            libraryAdapter.notifyDataSetChanged()
            updateSelectionCount(1)
        } else {
            binding.btnSelectionShare.visibility = View.GONE
            historyAdapter.isSelectionMode = true
            historyAdapter.selectedIds.clear()
            historyAdapter.selectedIds.add(initialId)
            historyAdapter.notifyDataSetChanged()
            updateSelectionCount(1)
        }
    }

    private fun exitSelectionMode() {
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
        binding.tvSelectionTitle.text = getString(R.string.selected_count, count)
    }

    private fun initSettings() {
        bindSettingsUi()

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
            if (!transferSettingsLocked()) {
                triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
                folderPickerLauncher.launch(null)
            }
        }

        binding.btnSettingsResetFolder.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transferSettingsLocked()) return@setOnClickListener
            val def = PreferencesManager.defaultDownloadDir()
            prefs.downloadDir = def
            binding.tvSettingsDownloadDir.text = def
            binding.tvFooterPath.text = def
            settingsApplied()
        }

        binding.btnSettingsMinusConcurrent.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transferSettingsLocked()) return@setOnClickListener
            if (prefs.concurrentDownloads > 1) {
                prefs.concurrentDownloads--
                binding.tvSettingsConcurrentCount.text = prefs.concurrentDownloads.toString()
                DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
                settingsApplied()
            }
        }

        binding.btnSettingsPlusConcurrent.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transferSettingsLocked()) return@setOnClickListener
            if (prefs.concurrentDownloads < 5) {
                prefs.concurrentDownloads++
                binding.tvSettingsConcurrentCount.text = prefs.concurrentDownloads.toString()
                DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
                settingsApplied()
            }
        }

        // Default Quality Spinner
        val qualityValues = listOf("ask", "best", "1080", "720", "480", "360")
        val qualityLabels = listOf(
            getString(R.string.quality_ask),
            getString(R.string.quality_best),
            "1080p",
            "720p",
            "480p",
            "360p"
        )
        val qualityAdapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, qualityLabels)
        binding.spDefaultQuality.adapter = qualityAdapter
        val curIndex = qualityValues.indexOf(prefs.defaultQuality).coerceAtLeast(0)
        binding.spDefaultQuality.setSelection(curIndex)

        binding.spDefaultQuality.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val chosen = qualityValues[position]
                if (prefs.defaultQuality != chosen) {
                    if (bindingSettings || transferSettingsLocked()) return
                    if (!acceptSettingsClick()) {
                        binding.spDefaultQuality.setSelection(qualityValues.indexOf(prefs.defaultQuality).coerceAtLeast(0))
                        return
                    }
                    prefs.defaultQuality = chosen
                    settingsApplied()
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        // Switches
        binding.switchPreferMp4.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) { bindSettingsUi(); return@setOnCheckedChangeListener }
            prefs.preferMp4 = isChecked
            settingsApplied()
            binding.cbDownloadMp4.isChecked = isChecked
        }

        binding.switchWifiOnly.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) { bindSettingsUi(); return@setOnCheckedChangeListener }
            prefs.wifiOnly = isChecked
            settingsApplied()
        }

        binding.switchAutoPaste.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) { bindSettingsUi(); return@setOnCheckedChangeListener }
            prefs.autoPaste = isChecked
            settingsApplied()
        }

        binding.switchSwipeDelete.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) { bindSettingsUi(); return@setOnCheckedChangeListener }
            prefs.swipeToDelete = isChecked
            settingsApplied()
        }

        binding.switchConfirmSwipeDelete.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) { bindSettingsUi(); return@setOnCheckedChangeListener }
            prefs.confirmSwipeDelete = isChecked
            settingsApplied()
        }

        binding.switchConfirmCancelDownload.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) { bindSettingsUi(); return@setOnCheckedChangeListener }
            prefs.confirmCancelDownload = isChecked
            settingsApplied()
        }

        binding.switchHapticFeedback.setOnCheckedChangeListener { _, isChecked ->
            if (bindingSettings) return@setOnCheckedChangeListener
            if (!acceptSettingsClick()) { bindSettingsUi(); return@setOnCheckedChangeListener }
            if (isChecked) prefs.hapticFeedback = true
            settingsApplied()
            prefs.hapticFeedback = isChecked
        }

        // Storage buttons
        binding.btnSettingsClearCache.setOnClickListener {
            if (clearingCache || !acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            clearingCache = true
            lifecycleScope.launch {
                try {
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                        FileUtils.clearCache(cacheDir, codeCacheDir)
                    }
                    updateCacheSizeDisplay()
                    ToastManager.show(binding.toastContainer, getString(R.string.cache_cleared))
                } finally { clearingCache = false }
            }
        }

        binding.btnSettingsClearCompleted.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            DownloadManager.clearFinished()
            ToastManager.show(binding.toastContainer, getString(R.string.completed_downloads_cleared))
        }

        binding.btnSettingsClearAllHistory.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.clear_history)
                .setMessage(R.string.clear_history_confirm)
                .setPositiveButton(R.string.clear_history) { _, _ ->
                    HistoryManager.clear(this)
                    ToastManager.show(binding.toastContainer, getString(R.string.clear_history))
                }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        binding.btnResetSettings.applyPressEffect()
        binding.btnResetSettings.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            if (transferSettingsLocked() || appearanceBusy) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.CONTEXT_CLICK)
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.reset_defaults)
                .setMessage(R.string.reset_defaults_confirm)
                .setPositiveButton(R.string.reset_defaults) { _, _ ->
                    if (transferSettingsLocked() || appearanceBusy) return@setPositiveButton
                    captureAppearance(true)
                    prefs.resetToDefaults()
                    DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
                    KodikApp.applyTheme(prefs.theme)
                    KodikApp.updateAppLocale(prefs.language)
                    binding.tvFooterPath.text = prefs.downloadDir
                    bindSettingsUi()
                    binding.root.postDelayed({ if (appearanceBusy) finishAppearance() }, 600)
                }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        // GitHub button
        binding.btnSettingsGithub.applyPressEffect()
        binding.btnSettingsGithub.setOnClickListener {
            if (!acceptSettingsClick()) return@setOnClickListener
            triggerHaptic(HapticFeedbackConstants.KEYBOARD_TAP)
            try {
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(getString(R.string.github_url)))
                startActivity(intent)
            } catch (e: Exception) {
                Log.w("MainActivity", "Cannot open GitHub", e)
            }
        }
    }

    private fun bindSettingsUi() {
        bindingSettings = true
        val accentColor = getColorFromAttr(R.attr.app_accent)
        val normalColor = getColorFromAttr(R.attr.app_text_muted)

        // Theme pills
        val curTheme = prefs.theme
        updatePill(binding.btnThemeAuto, curTheme == "auto", accentColor, normalColor)
        updatePill(binding.btnThemeLight, curTheme == "light", accentColor, normalColor)
        updatePill(binding.btnThemeDark, curTheme == "dark", accentColor, normalColor)

        // Language pills
        val curLang = prefs.language
        updatePill(binding.btnLangAuto, curLang == "auto", accentColor, normalColor)
        updatePill(binding.btnLangRu, curLang == "ru", accentColor, normalColor)
        updatePill(binding.btnLangEn, curLang == "en", accentColor, normalColor)

        // Downloads
        binding.tvSettingsDownloadDir.text = prefs.downloadDir
        binding.tvSettingsConcurrentCount.text = prefs.concurrentDownloads.toString()

        binding.switchPreferMp4.isChecked = prefs.preferMp4
        binding.switchWifiOnly.isChecked = prefs.wifiOnly
        binding.switchAutoPaste.isChecked = prefs.autoPaste

        // Gestures
        binding.switchSwipeDelete.isChecked = prefs.swipeToDelete
        binding.switchConfirmSwipeDelete.isChecked = prefs.confirmSwipeDelete
        binding.switchConfirmCancelDownload.isChecked = prefs.confirmCancelDownload
        binding.switchHapticFeedback.isChecked = prefs.hapticFeedback

        updateCacheSizeDisplay()
        bindingSettings = false
        updateSettingsAvailability()
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
        cacheSizeJob = lifecycleScope.launch {
            val size = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { getAppCacheSize() }
            if (label === binding.tvSettingsCacheSize) {
                label.text = getString(R.string.cache_size, FileUtils.formatFileSize(size))
            }
        }
    }

    private fun getAppCacheSize(): Long {
        var size = 0L
        try {
            cacheDir?.walkTopDown()?.filter { it.isFile }?.forEach { size += it.length() }
            codeCacheDir?.walkTopDown()?.filter { it.isFile }?.forEach { size += it.length() }
        } catch (_: Exception) {}
        return size
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
        updateSettingsAvailability()
        binding.btnDownload.isEnabled = false
        binding.tvFindText.setText(R.string.cancel)
        binding.ivFindIcon.setImageResource(R.drawable.ic_close)
        binding.pbResolving.visibility = View.VISIBLE
        binding.tvStatus.setText(R.string.resolving)
        switchTab(0)
        resolveJob = lifecycleScope.launch {
            try {
                val retry = com.shawniks.kodikdown.data.HistoryRetry.resolve(item, client::resolve)
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
                    updateSettingsAvailability()
                    binding.btnDownload.isEnabled = currentResolved != null
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

    private fun extractClipboardText(): String? {
        try {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            val clip = clipboard?.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val item = clip.getItemAt(0)
                val text = item.text?.toString() ?: item.uri?.toString()
                if (!text.isNullOrEmpty()) {
                    return extractUrlFromText(text)
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
                binding.etUrl.onTextContextMenuItem(android.R.id.paste)
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
        updateSettingsAvailability()
        binding.btnDownload.isEnabled = false
        binding.tvFindText.text = getString(R.string.cancel)
        binding.ivFindIcon.setImageResource(R.drawable.ic_close)
        binding.pbResolving.visibility = View.VISIBLE
        binding.tvStatus.text = getString(R.string.resolving)
        resolveJob =
            lifecycleScope.launch {
                try {
                    val resolved = client.resolve(rawUrl, translation)
                    if (generation == resolveGeneration) {
                        if (resolvedUrl != rawUrl) nameManuallyEdited = false
                        resolvedUrl = rawUrl
                        currentResolved = resolved
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
                        updateSettingsAvailability()
                        binding.btnDownload.isEnabled = currentResolved != null
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
        updateSettingsAvailability()
        currentResolved?.let { populateTranslations(it) }
        binding.btnDownload.isEnabled = currentResolved != null
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

        if (!nameManuallyEdited) {
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
        selectedTranslation = video.translation ?: video.translations.firstOrNull()
        if (video.translations.isNotEmpty()) {
            binding.rowTranslation.visibility = View.VISIBLE
            val titles = video.translations.map { it.title }
            val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, titles)
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
                        if (currentResolved === video && picked != selectedTranslation) {
                            startResolving(resolvedUrl, picked)
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

        // Check preferred quality from settings if applicable
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
        selectedVariant = activeVariant

        for ((index, variant) in variants.withIndex()) {
            val pill =
                TextView(this).apply {
                    val isBest = variant == variants.first()
                    val label =
                        if (isBest) "${variant.quality}p • ${getString(R.string.best_badge)}"
                        else "${variant.quality}p"
                    text = label
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
                        selectedVariant = variant
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

        // Check Wi-Fi Only constraint
        if (prefs.wifiOnly && !isWifiConnected()) {
            ToastManager.show(
                binding.toastContainer,
                getString(R.string.wifi_only_warning),
                isError = true
            )
            return
        }

        val variant = selectedVariant ?: currentResolved?.best ?: return
        val rawName = binding.etFileName.text.toString().trim()
        val safeName = FileUtils.safeFileName(rawName.ifEmpty { currentResolved?.title ?: "video" })
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
    private var duplicateDialog: androidx.appcompat.app.AlertDialog? = null

    private fun confirmExistingDownload(
        safeName: String,
        references: List<Pair<String?, String?>> = emptyList(),
        proceed: () -> Unit,
    ) {
        if (duplicateCheckJob?.isActive == true || duplicateDialog?.isShowing == true) return
        val library = LibraryManager.findExisting(safeName)
        val history = HistoryManager.items.value.filter {
            it.status == com.shawniks.kodikdown.data.DownloadStatus.FINISHED &&
                FileUtils.safeFileName(it.fileName).equals(safeName, ignoreCase = true)
        }
        val directory = prefs.downloadDir
        val candidates = references + listOfNotNull(library?.let { it.filePath to it.contentUri }) +
            history.map { it.savedPath to it.contentUri } +
            if (!directory.startsWith("content://")) listOf(File(directory, "$safeName.mp4").absolutePath to null) else emptyList()
        duplicateCheckJob = lifecycleScope.launch {
            val existing = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                candidates.distinct().firstOrNull { (path, uri) ->
                    com.shawniks.kodikdown.data.MediaFiles.exists(this@MainActivity, path, uri)
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
        val video = currentResolved ?: return
        if (variant !in video.variants) return
        val translationTitle = selectedTranslation?.title
        val downloadDir = prefs.downloadDir
        val sourceInput = resolvedUrl
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
        currentResolved = null
        selectedVariant = null
        nameManuallyEdited = false
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
