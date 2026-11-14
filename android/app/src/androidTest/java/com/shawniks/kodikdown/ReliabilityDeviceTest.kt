package com.shawniks.kodikdown

import android.test.InstrumentationTestCase
import com.shawniks.kodikdown.downloader.HlsDownloader
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.data.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import java.io.File
import java.net.ServerSocket
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

@Suppress("DEPRECATION")
class ReliabilityDeviceTest : InstrumentationTestCase() {
    fun testLargeHlsFragmentStreamsToDiskAndCleansTemporaryFiles(): Unit = runBlocking {
        val context = instrumentation.targetContext
        val output = File(context.cacheDir, "qa-large-fragment.mp4")
        val server = ServerSocket(0)
        val clip = instrumentation.context.assets.open("remux.ts").use { it.readBytes() }
        val nullPackets = ByteArray(188 * 256) { 0xff.toByte() }.apply {
            for (offset in indices step 188) {
                this[offset] = 0x47; this[offset + 1] = 0x1f; this[offset + 2] = 0xff.toByte(); this[offset + 3] = 0x10
            }
        }
        // A single >64 MiB transport-stream fragment used to hit the RAM limit.
        val paddingBlocks = 1600
        thread(isDaemon = true) {
            runCatching {
                repeat(2) {
                    server.accept().use { socket ->
                        val path = socket.getInputStream().bufferedReader().readLine().split(' ')[1]
                        val stream = socket.getOutputStream().buffered()
                        if (path.endsWith("m3u8")) {
                            val playlist = "#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:4,\nclip.ts\n#EXT-X-ENDLIST\n".toByteArray()
                            stream.write("HTTP/1.1 200 OK\r\nContent-Length: ${playlist.size}\r\nConnection: close\r\n\r\n".toByteArray())
                            stream.write(playlist)
                        } else {
                            val size = clip.size.toLong() + nullPackets.size.toLong() * paddingBlocks
                            stream.write("HTTP/1.1 200 OK\r\nContent-Length: $size\r\nConnection: close\r\n\r\n".toByteArray())
                            stream.write(clip)
                            repeat(paddingBlocks) { stream.write(nullPackets); if (it % 16 == 0) Thread.sleep(10) }
                        }
                        stream.flush()
                    }
                }
            }
        }
        try {
            withTimeout(60_000) {
                HlsDownloader().downloadHls("http://127.0.0.1:${server.localPort}/index.m3u8", output,
                    { false }, onProgress = { _, _, _, _ -> }, onProcessing = {
                        val runtime = Runtime.getRuntime()
                        android.util.Log.i("KodikQA", "Large fragment completed; Java heap used=${runtime.totalMemory() - runtime.freeMemory()}")
                    })
            }
            assertTrue(output.length() > 10_000)
            assertFalse(File(output.absolutePath + ".fragments").exists())
            assertFalse(File(output.absolutePath + ".part").exists())
            assertFalse(File(output.absolutePath + ".mux.part").exists())
        } finally { server.close(); output.delete() }
    }
    fun testInterruptedDirectDownloadResumesAtSavedOffset() = runBlocking {
        val data = instrumentation.context.assets.open("resume.mp4").use { it.readBytes() }
        val server = ServerSocket(0)
        val ranges = CopyOnWriteArrayList<String>()
        val waits = CopyOnWriteArrayList<Boolean>()
        val output = File(instrumentation.targetContext.cacheDir, "qa-resume.mp4")
        thread(isDaemon = true) {
            repeat(2) { index ->
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader()
                    var line: String?
                    var offset = 0
                    while (reader.readLine().also { line = it } != null && line != "") {
                        if (line!!.startsWith("Range:")) {
                            ranges.add(line!!)
                            offset = line!!.substringAfter("bytes=").substringBefore('-').toInt()
                        }
                    }
                    val header = if (index == 0) "HTTP/1.1 200 OK\r\nContent-Length: ${data.size}\r\n"
                        else "HTTP/1.1 206 Partial Content\r\nContent-Length: ${data.size-offset}\r\nContent-Range: bytes $offset-${data.size-1}/${data.size}\r\n"
                    val stream = socket.getOutputStream()
                    stream.write((header + "Connection: close\r\n\r\n").toByteArray())
                    if (index == 0) stream.write(data, 0, data.size / 2)
                    else stream.write(data, offset, data.size-offset)
                    stream.flush()
                }
            }
        }
        try {
            HlsDownloader().downloadDirectMp4("http://127.0.0.1:${server.localPort}/video.mp4",
                output, { false }, { _, _, _, _ -> }, onNetworkWait = { waits.add(it) })
            assertEquals(1, ranges.size)
            assertTrue(ranges[0].contains("bytes=${data.size/2}-"))
            assertTrue(waits.contains(true))
            assertTrue(data.contentEquals(output.readBytes()))
        } finally { server.close(); output.delete() }
    }

    fun testAssemblyCannotBeCancelledOrRemoved(): Unit = runBlocking {
        val context = instrumentation.targetContext
        val activity = instrumentation.startActivitySync(android.content.Intent(context, MainActivity::class.java)
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK or android.content.Intent.FLAG_ACTIVITY_CLEAR_TASK))
        val server = ServerSocket(0)
        val segment = instrumentation.context.assets.open("remux.ts").use { it.readBytes() }
        thread(isDaemon = true) {
            repeat(2) {
                server.accept().use { socket ->
                    val path = socket.getInputStream().bufferedReader().readLine().split(' ')[1]
                    val data = if (path.endsWith("m3u8"))
                        "#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:4,\nclip.ts\n#EXT-X-ENDLIST\n".toByteArray() else segment
                    socket.getOutputStream().apply {
                        write("HTTP/1.1 200 OK\r\nContent-Length: ${data.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(data); flush()
                    }
                }
            }
        }
        val protected = CompletableDeferred<Boolean>()
        val title = "QA protection ${java.util.UUID.randomUUID()}"
        val watcher = CoroutineScope(Dispatchers.Unconfined).launch {
            DownloadManager.items.collect { items ->
                val item = items.firstOrNull { it.title == title }
                if (item?.status == DownloadStatus.ASSEMBLING && !protected.isCompleted) {
                    DownloadManager.cancelDownload(item.id)
                    DownloadManager.removeDownload(item.id)
                    protected.complete(DownloadManager.items.value.any { it.id == item.id && it.status == DownloadStatus.ASSEMBLING })
                }
            }
        }
        var id = ""
        try {
            instrumentation.runOnMainSync {
                id = DownloadManager.enqueueDownload(context, title, "qa-protection", "http://127.0.0.1:${server.localPort}/index.m3u8",
                    360, false, "Download/KodikDown-QA")
            }
            assertTrue(withTimeout(10000) { protected.await() })
            val finished = withTimeout(10000) {
                DownloadManager.items.first { list -> list.any { it.id == id && it.isTerminal } }.first { it.id == id }
            }
            assertEquals(DownloadStatus.FINISHED, finished.status)
            finished.contentUri?.let { com.shawniks.kodikdown.util.FileUtils.deleteFile(context, it) }
        } finally {
            watcher.cancel(); server.close()
            if (id.isNotEmpty()) { DownloadManager.removeDownload(id); HistoryManager.remove(context, id) }
            LibraryManager.refresh(context, PreferencesManager(context).downloadDir)
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    fun testRemovedFilesAreUnavailableWithoutDeletingHistory() = runBlocking {
        val context = instrumentation.targetContext
        val file = File(context.cacheDir, "qa-availability.mp4").apply { writeText("sample") }
        val item = HistoryItem("qa-availability", "QA", "QA", "https://cdn/test", 360,
            savedPath = file.absolutePath)
        HistoryManager.recordOrUpdate(context, item)
        withTimeout(3000) { HistoryManager.items.first { list -> list.any { it.id == item.id } } }
        try {
            MediaFiles.refresh(context)
            assertTrue(MediaFiles.isAvailable(file.absolutePath, null))
            file.delete()
            MediaFiles.refresh(context)
            assertFalse(MediaFiles.isAvailable(file.absolutePath, null))
            assertTrue(HistoryManager.items.value.any { it.id == item.id })
        } finally { file.delete(); HistoryManager.remove(context, item.id) }
    }
}
