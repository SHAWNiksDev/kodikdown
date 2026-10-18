package com.shawniks.kodikdown

import android.Manifest
import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator
import android.view.animation.OvershootInterpolator
import android.view.inputmethod.EditorInfo
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.text.HtmlCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.SimpleItemAnimator
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.shawniks.kodikdown.data.AppSettings
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
import com.shawniks.kodikdown.ui.SettingsDialog
import com.shawniks.kodikdown.ui.ToastManager
import com.shawniks.kodikdown.util.FileUtils
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.File
import java.util.regex.Pattern

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: PreferencesManager
    private val client = KodikClient()

    private var resolveJob: Job? = null
    private var isResolving = false

    private var currentResolved: ResolvedVideo? = null
    private var selectedVariant: StreamVariant? = null
    private var selectedTranslation: Translation? = null
    private var nameManuallyEdited = false

    private lateinit var downloadAdapter: DownloadAdapter
    private lateinit var libraryAdapter: LibraryAdapter
    private lateinit var historyAdapter: HistoryAdapter
    private var currentTab = 0
    private var lastDownloadClickTime = 0L
    private var settingsDialog: SettingsDialog? = null

    private val folderPickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri: Uri? ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            val path = uri.path?.let {
                if (it.contains(":")) it.substringAfter(":") else it
            } ?: uri.toString()
            val finalPath = "/storage/emulated/0/$path"
            prefs.downloadDir = finalPath
            settingsDialog?.updateSelectedPath(finalPath)
            binding.tvFooterPath.text = finalPath
        }
    }

    private val requestNotificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ -> }

    override fun attachBaseContext(newBase: Context) {
        val p = PreferencesManager(newBase)
        super.attachBaseContext(KodikApp.applyLocale(newBase, p.language))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        prefs = PreferencesManager(this)
        requestNotificationPermission()

        HistoryManager.init(this)
        LibraryManager.refresh(this, prefs.downloadDir)

        initViews()
        initTabs()
        initDownloadsList()
        initLibrary()
        initHistory()
        handleIncomingIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                requestNotificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun initViews() {
        updateThemeIcon()
        binding.tvFooterPath.text = prefs.downloadDir

        // Apply interactive micro-interaction press effects
        binding.btnThemeToggle.applyPressEffect()
        binding.btnSettings.applyPressEffect()
        binding.btnClearUrl.applyPressEffect()
        binding.btnPaste.applyPressEffect()
        binding.btnFind.applyPressEffect()
        binding.btnDownload.applyPressEffect()
        binding.btnResultOpenFolder.applyPressEffect()
        binding.btnFooterOpenFolder.applyPressEffect()
        binding.btnClearFinished.applyPressEffect()

        // Theme toggle with smooth rotation, scale pop, and activity fade transition
        binding.btnThemeToggle.setOnClickListener {
            binding.btnThemeToggle.animate()
                .rotationBy(360f)
                .scaleX(0.7f)
                .scaleY(0.7f)
                .setDuration(220)
                .withEndAction {
                    val isDark = isDarkTheme()
                    val newTheme = if (isDark) "light" else "dark"
                    prefs.theme = newTheme
                    KodikApp.applyTheme(newTheme)
                    val intent = Intent(this, MainActivity::class.java).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION)
                    }
                    finish()
                    @Suppress("DEPRECATION")
                    overridePendingTransition(0, 0)
                    startActivity(intent)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                        overrideActivityTransition(OVERRIDE_TRANSITION_OPEN, android.R.anim.fade_in, android.R.anim.fade_out)
                    } else {
                        @Suppress("DEPRECATION")
                        overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
                    }
                }
                .start()
        }

        // Settings Dialog - clean click with press effect (no jerky rotation)
        binding.btnSettings.setOnClickListener {
            openSettings()
        }

        // URL input text watcher
        binding.etUrl.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                binding.btnClearUrl.visibility = if (s.isNullOrEmpty()) View.GONE else View.VISIBLE
            }
            override fun afterTextChanged(s: Editable?) {}
        })

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

        // Paste button
        binding.btnPaste.setOnClickListener {
            handlePaste()
        }

        // Find video button
        binding.btnFind.setOnClickListener {
            onFindClicked()
        }

        // Name edited watcher
        binding.etFileName.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                nameManuallyEdited = true
            }
            override fun afterTextChanged(s: Editable?) {}
        })

        // Download button
        binding.btnDownload.setOnClickListener {
            onDownloadClicked()
        }

        // Open folder buttons
        binding.btnResultOpenFolder.setOnClickListener { openDownloadFolder() }
        binding.btnFooterOpenFolder.setOnClickListener { openDownloadFolder() }

        // Clear finished
        binding.btnClearFinished.setOnClickListener {
            DownloadManager.clearFinished()
        }
    }

    private fun initDownloadsList() {
        downloadAdapter = DownloadAdapter(
            onCancelClicked = { item ->
                DownloadManager.cancelDownload(item.id)
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
            }
        )

        binding.rvDownloads.apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = downloadAdapter
            (itemAnimator as? SimpleItemAnimator)?.supportsChangeAnimations = false
        }

        lifecycleScope.launch {
            DownloadManager.items.collect { items ->
                downloadAdapter.submitList(items)
                if (items.isEmpty()) {
                    binding.tvDownloadsEmpty.visibility = View.VISIBLE
                    binding.rvDownloads.visibility = View.GONE
                } else {
                    binding.tvDownloadsEmpty.visibility = View.GONE
                    binding.rvDownloads.visibility = View.VISIBLE
                }
            }
        }
    }

    private fun initTabs() {
        binding.tabDownloader.setOnClickListener { switchTab(0) }
        binding.tabLibrary.setOnClickListener { switchTab(1) }
        binding.tabHistory.setOnClickListener { switchTab(2) }

        binding.tabDownloader.applyPressEffect()
        binding.tabLibrary.applyPressEffect()
        binding.tabHistory.applyPressEffect()

        updateTabUi(0)
    }

    private fun switchTab(index: Int) {
        if (currentTab == index) return
        currentTab = index

        val views = listOf(binding.viewDownloader, binding.viewLibrary, binding.viewHistory)
        views.forEachIndexed { i, view ->
            if (i == index) {
                view.visibility = View.VISIBLE
                view.alpha = 0f
                view.animate().alpha(1f).setDuration(160).start()
            } else {
                view.visibility = View.GONE
            }
        }

        updateTabUi(index)

        if (index == 1) {
            LibraryManager.refresh(this, prefs.downloadDir)
        } else if (index == 2) {
            HistoryManager.init(this)
        }
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
    }

    private fun initLibrary() {
        libraryAdapter = LibraryAdapter(
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
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.delete)
                    .setMessage(getString(R.string.delete_file_confirm, item.title))
                    .setPositiveButton(R.string.delete) { _, _ ->
                        lifecycleScope.launch {
                            val deleted = LibraryManager.deleteItem(this@MainActivity, item)
                            if (deleted) {
                                ToastManager.show(binding.toastContainer, getString(R.string.file_deleted))
                            }
                        }
                    }
                    .setNegativeButton(R.string.cancel, null)
                    .show()
            }
        )

        binding.rvLibrary.apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = libraryAdapter
        }

        binding.btnLibraryRefresh.applyPressEffect()
        binding.btnLibraryRefresh.setOnClickListener {
            binding.btnLibraryRefresh.animate().rotationBy(360f).setDuration(400).start()
            LibraryManager.refresh(this, prefs.downloadDir)
        }

        binding.btnLibraryOpenFolder.applyPressEffect()
        binding.btnLibraryOpenFolder.setOnClickListener {
            FileUtils.openFolder(this, prefs.downloadDir)
        }

        lifecycleScope.launch {
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
                    binding.tvLibraryCount.text = "${getString(R.string.video_count, list.size)} • $sizeStr"
                }
            }
        }
    }

    private fun initHistory() {
        historyAdapter = HistoryAdapter(
            onRedownloadClicked = { item ->
                val safeName = FileUtils.safeFileName(item.fileName.removeSuffix(".mp4"))
                DownloadManager.enqueueDownload(
                    context = this,
                    title = item.title,
                    fileName = safeName,
                    url = item.url,
                    quality = item.quality,
                    isMp4 = item.isMp4,
                    downloadDir = prefs.downloadDir,
                    translationTitle = item.translation
                )
                ToastManager.show(binding.toastContainer, getString(R.string.starting))
                switchTab(0)
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
                val clip = android.content.ClipData.newPlainText("video_url", item.url)
                clipboard?.setPrimaryClip(clip)
                ToastManager.show(binding.toastContainer, getString(R.string.link_copied))
            },
            onDeleteClicked = { item ->
                HistoryManager.remove(this, item.id)
            }
        )

        binding.rvHistory.apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = historyAdapter
        }

        binding.btnHistoryClearAll.applyPressEffect()
        binding.btnHistoryClearAll.setOnClickListener {
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.clear_history)
                .setMessage(R.string.clear_history_confirm)
                .setPositiveButton(R.string.clear_history) { _, _ ->
                    HistoryManager.clear(this)
                }
                .setNegativeButton(R.string.cancel, null)
                .show()
        }

        lifecycleScope.launch {
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

    private fun handleIncomingIntent(intent: Intent?) {
        if (intent == null) return
        val text = when (intent.action) {
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
        val iframeMatcher = Pattern.compile("""<iframe[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", Pattern.CASE_INSENSITIVE).matcher(text)
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
        val urlMatcher = Pattern.compile("""(https?://[^\s"'<>]+)""").matcher(text)
        if (urlMatcher.find()) {
            return urlMatcher.group(1) ?: text
        }

        return text
    }

    private fun extractClipboardText(): String? {
        try {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return null
            if (!clipboard.hasPrimaryClip()) return null
            val clip = clipboard.primaryClip ?: return null

            for (i in 0 until clip.itemCount) {
                val item = clip.getItemAt(i) ?: continue

                // 1. Explicit text
                val directText = item.text?.toString()?.trim()
                if (!directText.isNullOrEmpty()) {
                    return extractUrlFromText(directText)
                }

                // 2. Coerced text (handles URIs, Intents, Content Providers)
                val coerced = item.coerceToText(this)?.toString()?.trim()
                if (!coerced.isNullOrEmpty()) {
                    return extractUrlFromText(coerced)
                }

                // 3. Direct URI
                val uriStr = item.uri?.toString()?.trim()
                if (!uriStr.isNullOrEmpty()) {
                    return extractUrlFromText(uriStr)
                }

                // 4. HTML text
                val html = item.htmlText?.trim()
                if (!html.isNullOrEmpty()) {
                    val iframeMatcher = Pattern.compile("""<iframe[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", Pattern.CASE_INSENSITIVE).matcher(html)
                    if (iframeMatcher.find()) {
                        val src = iframeMatcher.group(1)?.trim()
                        if (!src.isNullOrEmpty()) return extractUrlFromText(src)
                    }
                    val hrefMatcher = Pattern.compile("""href\s*=\s*["']([^"']+)["']""", Pattern.CASE_INSENSITIVE).matcher(html)
                    if (hrefMatcher.find()) {
                        val href = hrefMatcher.group(1)?.trim()
                        if (!href.isNullOrEmpty()) return extractUrlFromText(href)
                    }
                    val clean = HtmlCompat.fromHtml(html, HtmlCompat.FROM_HTML_MODE_COMPACT).toString().trim()
                    if (clean.isNotEmpty()) return extractUrlFromText(clean)
                    return extractUrlFromText(html)
                }
            }

            // 5. Legacy clipboard text fallback
            @Suppress("DEPRECATION")
            val legacy = clipboard.text?.toString()?.trim()
            if (!legacy.isNullOrEmpty()) {
                return extractUrlFromText(legacy)
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

        // Fallback: use TextView's native paste action (works even when direct clipboard access is guarded by OS)
        val prevText = binding.etUrl.text?.toString().orEmpty()
        binding.etUrl.selectAll()
        val pasted = try {
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
        isResolving = true
        binding.tvFindText.text = getString(R.string.cancel)
        binding.ivFindIcon.setImageResource(R.drawable.ic_close)
        binding.pbResolving.visibility = View.VISIBLE
        binding.tvStatus.text = getString(R.string.resolving)

        resolveJob = lifecycleScope.launch {
            try {
                val resolved = client.resolve(rawUrl, translation)
                currentResolved = resolved
                displayResolvedVideo(resolved)
                binding.tvStatus.text = getString(R.string.hint)
            } catch (e: Exception) {
                hideResultCard()
                val msg = e.message ?: getString(R.string.network_error, "Unknown error")
                binding.tvStatus.text = msg
                ToastManager.show(binding.toastContainer, msg, isError = true)
            } finally {
                isResolving = false
                binding.tvFindText.text = getString(R.string.resolve)
                binding.ivFindIcon.setImageResource(R.drawable.ic_play)
                binding.pbResolving.visibility = View.GONE
            }
        }
    }

    private fun cancelResolving() {
        resolveJob?.cancel()
        isResolving = false
        binding.tvFindText.text = getString(R.string.resolve)
        binding.ivFindIcon.setImageResource(R.drawable.ic_play)
        binding.pbResolving.visibility = View.GONE
        binding.tvStatus.text = getString(R.string.hint)
    }

    private fun displayResolvedVideo(video: ResolvedVideo) {
        binding.tvResultTitle.text = video.title

        // Warning banner
        if (video.warnings.contains("proxy")) {
            binding.tvWarning.visibility = View.VISIBLE
        } else {
            binding.tvWarning.visibility = View.GONE
        }

        // File name
        if (!nameManuallyEdited) {
            binding.etFileName.setText(FileUtils.safeFileName(video.title))
        }

        // Translation dropdown
        if (video.translations.isNotEmpty()) {
            binding.rowTranslation.visibility = View.VISIBLE
            val titles = video.translations.map { it.title }
            val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, titles)
            binding.spTranslation.adapter = adapter

            val targetTranslation = video.translation
            val currentIndex = if (targetTranslation != null) {
                video.translations.indexOfFirst {
                    it.mediaId == targetTranslation.mediaId && it.contentHash == targetTranslation.contentHash
                }.coerceAtLeast(0)
            } else 0
            binding.spTranslation.setSelection(currentIndex)

            binding.spTranslation.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>?, view: View?, pos: Int, id: Long) {
                    val picked = video.translations[pos]
                    if (picked != selectedTranslation && selectedTranslation != null) {
                        selectedTranslation = picked
                        val url = binding.etUrl.text.toString().trim()
                        startResolving(url, picked)
                    } else {
                        selectedTranslation = picked
                    }
                }
                override fun onNothingSelected(parent: AdapterView<*>?) {}
            }
        } else {
            binding.rowTranslation.visibility = View.GONE
        }

        // Quality pills
        buildQualityPills(video.variants, video.defaultQuality)

        // Prefer MP4 check
        binding.cbDownloadMp4.isChecked = prefs.preferMp4

        // Smooth slide-in animation for Result Card
        if (binding.cardResult.visibility != View.VISIBLE) {
            binding.cardResult.alpha = 0f
            binding.cardResult.visibility = View.VISIBLE
            binding.cardResult.translationY = -dpToPx(16).toFloat()
            binding.cardResult.scaleX = 0.95f
            binding.cardResult.scaleY = 0.95f
            binding.cardResult.animate()
                .alpha(1f)
                .translationY(0f)
                .scaleX(1.0f)
                .scaleY(1.0f)
                .setDuration(350)
                .setInterpolator(OvershootInterpolator(1.3f))
                .start()
        }
    }

    private fun buildQualityPills(variants: List<StreamVariant>, defaultQuality: Int?) {
        binding.layoutQualityPills.removeAllViews()
        if (variants.isEmpty()) return

        val activeVariant = variants.first()
        selectedVariant = activeVariant

        for ((index, variant) in variants.withIndex()) {
            val pill = TextView(this).apply {
                val isBest = variant == variants.first()
                val label = if (isBest) "${variant.quality}p • ${getString(R.string.best_badge)}" else "${variant.quality}p"
                text = label
                textSize = 12f
                gravity = Gravity.CENTER
                setPadding(dpToPx(12), dpToPx(6), dpToPx(12), dpToPx(6))
                val params = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply {
                    marginEnd = dpToPx(6)
                }
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
        val now = System.currentTimeMillis()
        if (now - lastDownloadClickTime < 800) return
        lastDownloadClickTime = now

        val variant = selectedVariant ?: currentResolved?.best ?: return
        val rawName = binding.etFileName.text.toString().trim()
        val safeName = FileUtils.safeFileName(rawName.ifEmpty { currentResolved?.title ?: "video" })
        val preferMp4 = binding.cbDownloadMp4.isChecked

        val finalUrl = if (preferMp4 && variant.directMp4 != null) {
            variant.directMp4
        } else {
            variant.url
        }
        val isMp4 = preferMp4 && variant.directMp4 != null

        // 1. Check if already downloading in active downloads
        if (DownloadManager.isAlreadyActive(finalUrl, safeName)) {
            ToastManager.show(binding.toastContainer, getString(R.string.already_downloading))
            return
        }

        // 2. Check if already downloaded in Library or History
        val existingLib = LibraryManager.findExisting(safeName)
        val existingHistory = HistoryManager.findCompleted(finalUrl, safeName)

        if (existingLib != null || existingHistory != null) {
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.already_downloaded_title)
                .setMessage(getString(R.string.already_downloaded_message, safeName))
                .setPositiveButton(R.string.play) { _, _ ->
                    val pathOrUri = existingLib?.contentUri ?: existingLib?.filePath ?: existingHistory?.contentUri ?: existingHistory?.savedPath
                    if (!pathOrUri.isNullOrEmpty()) {
                        FileUtils.openFile(this, pathOrUri)
                    } else {
                        FileUtils.openFolder(this, prefs.downloadDir)
                    }
                }
                .setNegativeButton(R.string.download_again) { _, _ ->
                    startDownloadExecution(variant, safeName, finalUrl, isMp4)
                }
                .setNeutralButton(R.string.cancel, null)
                .show()
            return
        }

        startDownloadExecution(variant, safeName, finalUrl, isMp4)
    }

    private fun startDownloadExecution(
        variant: StreamVariant,
        safeName: String,
        finalUrl: String,
        isMp4: Boolean
    ) {
        DownloadManager.enqueueDownload(
            context = this,
            title = currentResolved?.title ?: safeName,
            fileName = safeName,
            url = finalUrl,
            quality = variant.quality,
            isMp4 = isMp4,
            downloadDir = prefs.downloadDir,
            translationTitle = selectedTranslation?.title
        )

        ToastManager.show(binding.toastContainer, getString(R.string.starting))
    }

    private fun hideResultCard() {
        if (binding.cardResult.visibility == View.VISIBLE) {
            binding.cardResult.animate()
                .alpha(0f)
                .translationY(-dpToPx(10).toFloat())
                .setDuration(200)
                .setListener(object : AnimatorListenerAdapter() {
                    override fun onAnimationEnd(animation: Animator) {
                        binding.cardResult.visibility = View.GONE
                    }
                })
                .start()
        }
        currentResolved = null
        selectedVariant = null
        nameManuallyEdited = false
    }

    private fun openDownloadFolder() {
        FileUtils.openFolder(this, prefs.downloadDir)
    }

    private fun openSettings() {
        settingsDialog = SettingsDialog(
            context = this,
            onSaved = { oldSettings, updated ->
                binding.tvFooterPath.text = updated.downloadDir
                DownloadManager.maxConcurrentDownloads = updated.concurrentDownloads
                binding.cbDownloadMp4.isChecked = updated.preferMp4

                val themeChanged = oldSettings.theme != updated.theme
                val langChanged = oldSettings.language != updated.language

                if (themeChanged || langChanged) {
                    if (themeChanged) {
                        KodikApp.applyTheme(updated.theme)
                    }
                    val intent = Intent(this, MainActivity::class.java).apply {
                        addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    finish()
                    @Suppress("DEPRECATION")
                    overridePendingTransition(0, 0)
                    startActivity(intent)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                        overrideActivityTransition(OVERRIDE_TRANSITION_OPEN, android.R.anim.fade_in, android.R.anim.fade_out)
                    } else {
                        @Suppress("DEPRECATION")
                        overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
                    }
                } else {
                    ToastManager.show(binding.toastContainer, getString(R.string.settings_saved))
                }
            },
            onPickFolder = {
                folderPickerLauncher.launch(null)
            }
        )
        settingsDialog?.show()
    }

    private fun updateThemeIcon() {
        if (isDarkTheme()) {
            binding.btnThemeToggle.setImageResource(R.drawable.ic_sun)
        } else {
            binding.btnThemeToggle.setImageResource(R.drawable.ic_moon)
        }
    }

    private fun isDarkTheme(): Boolean {
        return when (prefs.theme) {
            "dark" -> true
            "light" -> false
            else -> {
                val mode = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK
                mode == Configuration.UI_MODE_NIGHT_YES
            }
        }
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
