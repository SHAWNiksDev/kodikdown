package com.shawniks.kodikdown

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.test.InstrumentationTestCase
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import androidx.recyclerview.widget.RecyclerView
import com.shawniks.kodikdown.data.*
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.net.ServerSocket
import kotlin.concurrent.thread
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first

@Suppress("DEPRECATION")
class HistoryDeviceTest : InstrumentationTestCase() {
    private fun main(action: () -> Unit) {
        var failure: Throwable? = null
        instrumentation.runOnMainSync { try { action() } catch (error: Throwable) { failure = error } }
        failure?.let { throw it }
    }

    fun testHistoryCopiesOriginalAndConfirmsOnlyExistingFiles(): Unit = runBlocking {
        val context = instrumentation.targetContext
        val prefs = PreferencesManager(context)
        val originalSettings = prefs.getSettings()
        val directory = prefs.downloadDir
        prefs.autoPaste = false
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        main { activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
        val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        var originalClip: android.content.ClipData? = null
        main { originalClip = clipboard.primaryClip }
        val server = ServerSocket(0)
        val bytes = instrumentation.context.assets.open("resume.mp4").use { it.readBytes() }
        val file = File(context.cacheDir, "qa-history-existing.mp4").apply { writeBytes(bytes) }
        val source = "<iframe src=\"https://kodikplayer.com/video/42/abcdef0123456789/720p?episode=2\"></iframe>"
        val title = "QA history ${java.util.UUID.randomUUID()}"
        val item = HistoryItem("qa-history-${java.util.UUID.randomUUID()}", title, "qa-history-${java.util.UUID.randomUUID()}",
            "http://127.0.0.1:${server.localPort}/video.mp4", 720, isMp4 = true,
            savedPath = file.absolutePath, sourceInput = source)
        var downloadedId: String? = null
        thread(isDaemon = true) {
            runCatching {
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader()
                    while (reader.readLine().orEmpty().isNotEmpty()) { }
                    socket.getOutputStream().apply {
                        write("HTTP/1.1 200 OK\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(bytes); flush()
                    }
                }
            }
        }
        try {
            HistoryManager.recordOrUpdate(context, item)
            withTimeout(3000) { HistoryManager.items.first { list -> list.any { it.id == item.id } } }
            MediaFiles.refresh(context)
            main {
                prefs.downloadDir = "Download/KodikDown-QA"
                prefs.autoPaste = true
                prefs.wifiOnly = false
                activity.findViewById<View>(R.id.tabHistory).performClick()
            }
            Thread.sleep(300)
            main {
                val row = activity.findViewById<RecyclerView>(R.id.rvHistory).getChildAt(0)
                row.findViewById<View>(R.id.btnHistoryCopy).performClick()
                assertEquals(source, clipboard.primaryClip!!.getItemAt(0).text.toString())
                val play = row.findViewById<View>(R.id.btnHistoryPlay)
                val retry = row.findViewById<View>(R.id.btnHistoryRedownload)
                assertTrue(retry.left - play.right >= (7 * activity.resources.displayMetrics.density).toInt())
                retry.performClick()
            }
            val automation = instrumentation.uiAutomation
            var cancel: AccessibilityNodeInfo? = null
            val deadline = System.currentTimeMillis() + 3000
            while (cancel == null && System.currentTimeMillis() < deadline) {
                cancel = automation.rootInActiveWindow?.findAccessibilityNodeInfosByText(activity.getString(R.string.cancel))
                    ?.firstOrNull { it.isClickable && it.className.toString().contains("Button") }
                if (cancel == null) Thread.sleep(80)
            }
            assertNotNull("Existing files must prompt before redownloading", cancel)
            assertFalse(DownloadManager.items.value.any { it.title == title })
            cancel!!.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            Thread.sleep(200)
            file.delete()
            // Legacy entries without player input must still support their existing stream.
            val legacy = item.copy(id = item.id + "-legacy", title = "$title legacy", sourceInput = null)
            HistoryManager.recordOrUpdate(context, legacy)
            withTimeout(3000) { HistoryManager.items.first { list -> list.any { it.id == legacy.id } } }
            val rowDeadline = System.currentTimeMillis() + 10000
            var boundLegacy = false
            var retryRow: View? = null
            main { activity.findViewById<RecyclerView>(R.id.rvHistory).scrollToPosition(0) }
            while (!boundLegacy && System.currentTimeMillis() < rowDeadline) {
                main {
                    val list = activity.findViewById<RecyclerView>(R.id.rvHistory)
                    val adapter = list.adapter as com.shawniks.kodikdown.ui.HistoryAdapter
                    retryRow = list.findViewHolderForAdapterPosition(0)?.itemView
                    boundLegacy = adapter.currentList.firstOrNull()?.id == legacy.id &&
                        retryRow?.findViewById<android.widget.TextView>(R.id.tvHistoryTitle)?.text.toString() == legacy.title &&
                        list.itemAnimator?.isRunning != true
                }
                if (!boundLegacy) Thread.sleep(40)
            }
            main {
                val list = activity.findViewById<RecyclerView>(R.id.rvHistory)
                val adapter = list.adapter as com.shawniks.kodikdown.ui.HistoryAdapter
                assertTrue("Legacy retry row was not bound: first=${adapter.currentList.firstOrNull()?.id}, " +
                    "children=${list.childCount}, animating=${list.itemAnimator?.isRunning}, " +
                    "title=${retryRow?.findViewById<android.widget.TextView>(R.id.tvHistoryTitle)?.text}", boundLegacy)
            }
            main {
                retryRow!!.findViewById<View>(R.id.btnHistoryRedownload).performClick()
            }
            val result = withTimeout(10000) {
                DownloadManager.items.first { list -> list.any { it.title == legacy.title && it.isTerminal } }
                    .first { it.title == legacy.title }
            }
            downloadedId = result.id
            assertEquals(DownloadStatus.FINISHED, result.status)
            assertNull(result.sourceInput)
            withTimeout(3000) {
                HistoryManager.items.first { list -> list.any { it.id == result.id && it.sourceInput == null && it.status == DownloadStatus.FINISHED } }
            }
            val stored = File(context.filesDir, "download_history.json")
            val diskDeadline = System.currentTimeMillis() + 3000
            var persisted = false
            while (!persisted && System.currentTimeMillis() < diskDeadline) {
                persisted = runCatching {
                    val json = org.json.JSONArray(stored.readText())
                    (0 until json.length()).any { index ->
                        val entry = json.getJSONObject(index)
                        entry.optString("id") == item.id && entry.optString("sourceInput") == source
                    }
                }.getOrDefault(false)
                if (!persisted) Thread.sleep(40)
            }
            assertTrue("Original input must survive saving history", persisted)
            result.contentUri?.let { FileUtils.deleteFile(context, it) }
        } finally {
            file.delete(); server.close()
            HistoryManager.remove(context, item.id)
            HistoryManager.remove(context, item.id + "-legacy")
            downloadedId?.let { DownloadManager.removeDownload(it); HistoryManager.remove(context, it) }
            main {
                prefs.saveSettings(originalSettings)
                originalClip?.let { clipboard.setPrimaryClip(it) } ?: run {
                    if (android.os.Build.VERSION.SDK_INT >= 28) clipboard.clearPrimaryClip()
                    else clipboard.setPrimaryClip(android.content.ClipData.newPlainText("", ""))
                }
                activity.finish()
            }
            LibraryManager.refresh(context, directory)
        }
    }
}
