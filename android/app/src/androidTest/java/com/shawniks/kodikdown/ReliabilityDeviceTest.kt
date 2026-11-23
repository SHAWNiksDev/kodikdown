package com.shawniks.kodikdown

import android.content.Intent
import android.test.InstrumentationTestCase
import android.util.Log
import com.shawniks.kodikdown.data.*
import com.shawniks.kodikdown.downloader.DownloadManager
import com.shawniks.kodikdown.downloader.HlsDownloader
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first

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
                        Log.i("KodikQA", "Large fragment completed; Java heap used=${runtime.totalMemory() - runtime.freeMemory()}")
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
        val validators = CopyOnWriteArrayList<String>()
        val referers = CopyOnWriteArrayList<String>()
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
                        if (line!!.startsWith("If-Range:", ignoreCase = true)) {
                            validators.add(line!!.substringAfter(':').trim())
                        }
                        if (line!!.startsWith("Referer:", ignoreCase = true)) {
                            referers.add(line!!.substringAfter(':').trim())
                        }
                    }
                    val header = if (index == 0) "HTTP/1.1 200 OK\r\nContent-Length: ${data.size}\r\n"
                        else "HTTP/1.1 206 Partial Content\r\nContent-Length: ${data.size-offset}\r\nContent-Range: bytes $offset-${data.size-1}/${data.size}\r\n"
                    val stream = socket.getOutputStream()
                    stream.write((header + "ETag: \"fixture-v1\"\r\nConnection: close\r\n\r\n").toByteArray())
                    if (index == 0) stream.write(data, 0, data.size / 2)
                    else stream.write(data, offset, data.size-offset)
                    stream.flush()
                }
            }
        }
        try {
            val referer = "https://player.example/watch"
            HlsDownloader().downloadDirectMp4("http://127.0.0.1:${server.localPort}/video.mp4",
                output, { false }, { _, _, _, _ -> }, onNetworkWait = { waits.add(it) }, referer = referer)
            assertEquals(1, ranges.size)
            assertTrue(ranges[0].contains("bytes=${data.size/2}-"))
            assertEquals(listOf("\"fixture-v1\""), validators)
            assertTrue(waits.contains(true))
            assertEquals(listOf(referer, referer), referers)
            assertTrue(data.contentEquals(output.readBytes()))
        } finally { server.close(); output.delete() }
    }

    fun testRelativeHlsLinksUseBothRedirectDestinations(): Unit = runBlocking {
        val output = File(instrumentation.targetContext.cacheDir, "qa-redirect.mp4")
        val clip = instrumentation.context.assets.open("remux.ts").use { it.readBytes() }
        val requests = CopyOnWriteArrayList<String>()
        ServerSocket(0).use { server ->
            val worker = thread(isDaemon = true) {
                try {
                    repeat(5) {
                        server.accept().use { socket ->
                            val path = socket.getInputStream().bufferedReader().readLine().split(' ')[1]
                            requests.add(path)
                            when (path) {
                                "/entry.m3u8" -> reply(socket, "301 Moved Permanently", "/master/main.m3u8")
                                "/master/main.m3u8" -> reply(socket, body =
                                    "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500,RESOLUTION=640x360\nvideo.m3u8\n".toByteArray())
                                "/master/video.m3u8" -> reply(socket, "302 Found", "/media/video.m3u8")
                                "/media/video.m3u8" -> reply(socket, body =
                                    "#EXTM3U\n#EXTINF:4,\nvideo.ts\n#EXT-X-ENDLIST\n".toByteArray())
                                "/media/video.ts" -> reply(socket, body = clip)
                                else -> reply(socket, "404 Not Found")
                            }
                        }
                    }
                } catch (e: SocketException) {
                    if (!server.isClosed) throw e
                }
            }
            try {
                withTimeout(10_000) {
                    HlsDownloader().downloadHls("http://127.0.0.1:${server.localPort}/entry.m3u8", output,
                        { false }, onProgress = { _, _, _, _ -> })
                }
                assertEquals(listOf("/entry.m3u8", "/master/main.m3u8", "/master/video.m3u8",
                    "/media/video.m3u8", "/media/video.ts"), requests)
                assertTrue(output.length() > 0)
            } finally {
                server.close()
                worker.join(1000)
                output.delete()
            }
        }
    }

    private fun reply(socket: Socket, status: String = "200 OK", location: String? = null,
        body: ByteArray = byteArrayOf()) {
        val redirect = location?.let { "Location: $it\r\n" }.orEmpty()
        socket.getOutputStream().buffered().apply {
            write("HTTP/1.1 $status\r\n${redirect}Content-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
            write(body)
            flush()
        }
    }

    fun testAssemblyCannotBeCancelledOrRemoved(): Unit = runBlocking {
        val context = instrumentation.targetContext
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
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
        val title = "QA protection ${UUID.randomUUID()}"
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
                    360, false, qaDownloadDirectory())
            }
            assertTrue(withTimeout(10000) { protected.await() })
            val finished = withTimeout(10000) {
                DownloadManager.items.first { list -> list.any { it.id == id && it.isTerminal } }.first { it.id == id }
            }
            assertEquals(DownloadStatus.FINISHED, finished.status)
            finished.contentUri?.let { FileUtils.deleteFile(context, it) }
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
