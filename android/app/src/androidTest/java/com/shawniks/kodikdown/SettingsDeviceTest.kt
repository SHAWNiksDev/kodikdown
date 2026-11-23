package com.shawniks.kodikdown

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import android.view.inputmethod.InputMethodManager
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.HistoryManager
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.downloader.DownloadService
import com.shawniks.kodikdown.ui.SettingsSaveIndicatorView
import com.shawniks.kodikdown.util.FileUtils
import java.net.ServerSocket
import kotlin.concurrent.thread

@Suppress("DEPRECATION")
class SettingsDeviceTest : InstrumentationTestCase() {
    fun testSettingsShowsInstalledVersion() {
        val context = instrumentation.targetContext
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        try {
            main {
                activity.findViewById<View>(R.id.tabSettings).performClick()
                val installedVersion = context.packageManager.getPackageInfo(context.packageName, 0).versionName
                val label = activity.findViewById<TextView>(R.id.tvSettingsAppVersion)
                assertEquals("KodikDown v$installedVersion", label.text.toString())
            }
        } finally {
            main { activity.finish() }
        }
    }

    fun testSettingsSaveIndicatorIsSingleAndStopsAfterSaving() {
        val context = instrumentation.targetContext
        val prefs = PreferencesManager(context)
        val original = prefs.getSettings()
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        val indicator = activity.findViewById<SettingsSaveIndicatorView>(R.id.settingsSaveIndicator)
        try {
            main {
                activity.findViewById<View>(R.id.tabSettings).performClick()
                val button = if (prefs.concurrentDownloads < 5) R.id.btnSettingsPlusConcurrent else R.id.btnSettingsMinusConcurrent
                activity.findViewById<View>(button).performClick()
                assertEquals(activity.getString(R.string.settings_saving), indicator.contentDescription)
                assertEquals(0, activity.findViewById<ViewGroup>(R.id.toastContainer).childCount)
                val github = activity.findViewById<TextView>(R.id.btnSettingsGithub)
                assertNotNull(github.compoundDrawablesRelative[0])
                assertEquals("SHAWNiks", activity.getString(R.string.author))
                repeat(25) { indicator.pulse() }
            }
            Thread.sleep(800)
            main {
                assertEquals(activity.getString(R.string.settings_saved), indicator.contentDescription)
                indicator.pulse()
            }
            Thread.sleep(800)
            main {
                // The old pulse's hide callback must not hide the new one.
                assertEquals(activity.getString(R.string.settings_saved), indicator.contentDescription)
                assertEquals(0, activity.findViewById<ViewGroup>(R.id.toastContainer).childCount)
            }
            Thread.sleep(650)
            main { assertNull(indicator.contentDescription) }
        } finally {
            main { prefs.saveSettings(original); activity.finish() }
        }
    }

    fun testKeyboardClosesWhenLeavingDownloader() {
        val context = instrumentation.targetContext
        val prefs = PreferencesManager(context)
        val original = prefs.getSettings()
        prefs.autoPaste = false
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        val input = activity.findViewById<View>(R.id.etUrl)
        val keyboard = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
        fun keyboardVisible(): Boolean {
            var visible = false
            main { visible = ViewCompat.getRootWindowInsets(activity.window.decorView)
                ?.isVisible(WindowInsetsCompat.Type.ime()) == true }
            return visible
        }
        try {
            main {
                activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                activity.findViewById<View>(R.id.tabDownloader).performClick()
                input.requestFocus()
            }
            var showRequested = false
            val openDeadline = System.currentTimeMillis() + 5000
            while (!keyboardVisible() && System.currentTimeMillis() < openDeadline) {
                main {
                    if (!showRequested && input.hasWindowFocus() && keyboard.isActive(input)) {
                        showRequested = keyboard.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT)
                    }
                }
                Thread.sleep(50)
            }
            assertTrue("Keyboard must be visible before checking tab dismissal", keyboardVisible())
            main { activity.findViewById<View>(R.id.tabSettings).performClick() }
            val closeDeadline = System.currentTimeMillis() + 5000
            while (keyboardVisible() && System.currentTimeMillis() < closeDeadline) Thread.sleep(50)
            assertFalse("Keyboard obscures settings after switching tabs", keyboardVisible())
        } finally { main { prefs.saveSettings(original); activity.finish() } }
    }
    private fun main(action: () -> Unit) {
        var failure: Throwable? = null
        instrumentation.runOnMainSync {
            try { action() } catch (error: Throwable) { failure = error }
        }
        failure?.let { throw it }
    }

    fun testCancellationConfirmationPreferencePersists() {
        val context = instrumentation.targetContext
        val prefs = PreferencesManager(context)
        val original = prefs.getSettings()
        try {
            prefs.confirmCancelDownload = false
            assertFalse(PreferencesManager(context).confirmCancelDownload)
            assertFalse(prefs.getSettings().confirmCancelDownload)
            prefs.saveSettings(original.copy(confirmCancelDownload = true))
            assertTrue(PreferencesManager(context).confirmCancelDownload)
        } finally { prefs.saveSettings(original) }
    }

    fun testAppearanceSpamProgressAndProtectedDownloads() {
        val prefs = PreferencesManager(instrumentation.targetContext)
        val original = prefs.getSettings()
        prefs.autoPaste = false
        val activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext,
            MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        main { activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
        var jobId = ""
        val server = ServerSocket(0)
        try {
            main { activity.findViewById<View>(R.id.tabSettings).performClick() }
            main {
                assertEquals(0, activity.resources.getIdentifier("btnThemeToggle", "id", activity.packageName))
                assertEquals(0, activity.resources.getIdentifier("btnApplySettings", "id", activity.packageName))
                activity.findViewById<View>(R.id.btnThemeLight).performClick()
                repeat(30) {
                    activity.findViewById<View>(R.id.btnThemeDark).performClick()
                    activity.findViewById<View>(R.id.btnLangEn).performClick()
                }
            }
            Thread.sleep(700)
            main {
                assertFalse(activity.isFinishing)
                assertEquals("Theme changes must use the corner indicator", 0,
                    activity.findViewById<ViewGroup>(R.id.toastContainer).childCount)
                assertTrue(activity.findViewById<View>(R.id.btnThemeDark).isEnabled)
                activity.findViewById<View>(R.id.btnLangEn).performClick()
            }
            Thread.sleep(700)
            main {
                assertEquals("Settings applied", activity.getString(R.string.settings_saved))
                assertEquals("Language changes must use the corner indicator", 0,
                    activity.findViewById<ViewGroup>(R.id.toastContainer).childCount)
                assertEquals(View.VISIBLE, activity.findViewById<View>(R.id.viewSettings).visibility)
                activity.findViewById<View>(R.id.btnLangRu).performClick()
            }
            Thread.sleep(700)
            main {
                assertEquals("Настройки применены", activity.getString(R.string.settings_saved))
                assertEquals("Language changes must not leave a success toast", 0,
                    activity.findViewById<ViewGroup>(R.id.toastContainer).childCount)
                activity.findViewById<View>(R.id.btnThemeDark).performClick()
            }
            Thread.sleep(700)
            val segment = instrumentation.context.assets.open("remux.ts").use { it.readBytes() }
            val manifest = "#EXTM3U\n#EXT-X-TARGETDURATION:4\n" +
                (0..3).joinToString("") { "#EXTINF:4,\n$it.ts\n" } + "#EXT-X-ENDLIST\n"
            thread(isDaemon = true) {
                while (!server.isClosed) {
                    try {
                        val socket = server.accept()
                        thread(isDaemon = true) {
                            socket.use {
                                val path = it.getInputStream().bufferedReader().readLine().split(' ')[1]
                                val data = if (path.endsWith("m3u8")) manifest.toByteArray() else segment
                                val index = path.removePrefix("/").substringBefore('.').toIntOrNull()
                                if (index != null) Thread.sleep(if (index == 0) 100 else 8000)
                                runCatching {
                                    it.getOutputStream().apply {
                                        write("HTTP/1.1 200 OK\r\nContent-Length: ${data.size}\r\nConnection: close\r\n\r\n".toByteArray())
                                        write(data)
                                        flush()
                                    }
                                }
                            }
                        }
                    } catch (_: Exception) { break }
                }
            }
            main {
                prefs.swipeToDelete = true
                prefs.confirmCancelDownload = true
                jobId = DownloadManager.enqueueDownload(activity, "QA progress", "qa-progress",
                    "http://127.0.0.1:${server.localPort}/playlist.m3u8", 360, false,
                    qaDownloadDirectory())
            }
            val deadline = System.currentTimeMillis() + 5000
            while (System.currentTimeMillis() < deadline &&
                DownloadManager.items.value.first { it.id == jobId }.downloadedFragments == 0) Thread.sleep(50)
            instrumentation.waitForIdleSync()
            main {
                val item = DownloadManager.items.value.first { it.id == jobId }
                assertTrue(HistoryManager.items.value.any { it.id == jobId && it.status == DownloadStatus.DOWNLOADING })
                HistoryManager.remove(activity, jobId)
                assertEquals(4, item.fragmentCount)
                assertEquals(1, item.downloadedFragments)
                assertEquals(0.25f, item.progress)
                assertFalse(activity.findViewById<View>(R.id.btnSettingsPlusConcurrent).isEnabled)
                assertFalse(activity.findViewById<View>(R.id.btnSettingsBrowseFolder).isEnabled)
                assertTrue(activity.findViewById<View>(R.id.btnThemeLight).isEnabled)
                activity.findViewById<View>(R.id.tabDownloader).performClick()
            }
            Thread.sleep(1200)
            val manager = instrumentation.targetContext.getSystemService(NotificationManager::class.java)
            val notificationDeadline = System.currentTimeMillis() + 3000
            var notification: Notification? = null
            while (notification == null && System.currentTimeMillis() < notificationDeadline) {
                notification = manager.activeNotifications.firstOrNull {
                    it.id == DownloadService.NOTIFICATION_ID
                }?.notification
                if (notification == null) Thread.sleep(60)
            }
            assertNotNull("Download notification must be visible immediately", notification)
            assertTrue(notification!!.extras.getString(Notification.EXTRA_TEXT).orEmpty().contains("25%"))
            assertTrue(notification.actions.isNullOrEmpty())
            assertTrue(HistoryManager.items.value.any { it.id == jobId })
            main {
                val list = activity.findViewById<RecyclerView>(R.id.rvDownloads)
                val row = list.getChildAt(0)
                val progress = row.findViewById<LinearProgressIndicator>(R.id.progressBar)
                assertEquals(View.VISIBLE, progress.visibility)
                assertFalse(progress.isIndeterminate)
                assertEquals(25, progress.progress)
                assertTrue(row.findViewById<TextView>(R.id.tvStatus).text.contains("25%"))
                assertFalse(row.performLongClick())
                assertEquals(View.GONE, activity.findViewById<View>(R.id.selectionBar).visibility)
            }
            Thread.sleep(150)
            val location = IntArray(2)
            var width = 0
            var height = 0
            main {
                val row = activity.findViewById<RecyclerView>(R.id.rvDownloads).getChildAt(0)
                assertTrue("Swipe must stay inside the QA app", activity.hasWindowFocus())
                row.getLocationOnScreen(location)
                width = row.width
                height = row.height
            }
            val now = SystemClock.uptimeMillis()
            for (step in 0..12) {
                val action = when (step) {
                    0 -> MotionEvent.ACTION_DOWN
                    12 -> MotionEvent.ACTION_UP
                    else -> MotionEvent.ACTION_MOVE
                }
                val event = MotionEvent.obtain(now, now + step * 20L, action,
                    location[0] + width * (0.8f - step * 0.06f),
                    location[1] + height / 2f, 0)
                instrumentation.sendPointerSync(event)
                event.recycle()
                Thread.sleep(20)
            }
            Thread.sleep(500)
            assertTrue(DownloadManager.items.value.any { it.id == jobId && !it.isTerminal })
            DownloadManager.removeDownload(jobId)
            assertTrue(DownloadManager.items.value.any { it.id == jobId && !it.isTerminal })
            main {
                val row = activity.findViewById<RecyclerView>(R.id.rvDownloads).getChildAt(0)
                assertEquals(View.GONE, activity.findViewById<View>(R.id.selectionBar).visibility)
                assertEquals(View.VISIBLE, row.findViewById<View>(R.id.btnCancel).visibility)
                row.findViewById<View>(R.id.btnCancel).performClick()
            }
            fun dialogButton(text: String): AccessibilityNodeInfo {
                val deadline = System.currentTimeMillis() + 2500
                while (System.currentTimeMillis() < deadline) {
                    val button = instrumentation.uiAutomation.rootInActiveWindow
                        ?.takeIf { it.packageName == activity.packageName }
                        ?.findAccessibilityNodeInfosByText(text)
                        ?.firstOrNull { it.isClickable && it.className.toString().contains("Button") }
                    if (button != null) return button
                    Thread.sleep(70)
                }
                throw AssertionError("Missing cancellation confirmation button: $text")
            }
            dialogButton(activity.getString(R.string.keep_downloading))
                .performAction(AccessibilityNodeInfo.ACTION_CLICK)
            Thread.sleep(180)
            assertTrue("Declining cancellation must keep the download active", DownloadManager.isActive(jobId))
            main {
                val row = activity.findViewById<RecyclerView>(R.id.rvDownloads).getChildAt(0)
                repeat(5) { row.findViewById<View>(R.id.btnCancel).performClick() }
            }
            assertTrue("Showing confirmation must not stop the download", DownloadManager.isActive(jobId))
            dialogButton(activity.getString(R.string.stop_download))
                .performAction(AccessibilityNodeInfo.ACTION_CLICK)
            val deadlineAfterCancel = System.currentTimeMillis() + 3000
            while (System.currentTimeMillis() < deadlineAfterCancel && DownloadManager.isActive(jobId)) Thread.sleep(50)
            assertEquals(DownloadStatus.CANCELLED,
                DownloadManager.items.value.first { it.id == jobId }.status)
        } finally {
            server.close()
            if (jobId.isNotEmpty()) {
                DownloadManager.cancelDownload(jobId)
                val cleanupDeadline = System.currentTimeMillis() + 3000
                while (DownloadManager.isActive(jobId) && System.currentTimeMillis() < cleanupDeadline) Thread.sleep(30)
                DownloadManager.items.value.firstOrNull { it.id == jobId }?.contentUri?.let {
                    FileUtils.deleteFile(instrumentation.targetContext, it)
                }
                DownloadManager.removeDownload(jobId)
                HistoryManager.remove(instrumentation.targetContext, jobId)
            }
            main {
                prefs.saveSettings(original)
                KodikApp.applyTheme(original.theme)
                KodikApp.updateAppLocale(original.language)
                activity.finish()
            }
        }
    }
}
