package com.shawniks.kodikdown

import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class CacheCleanupTest {
    @get:Rule val temporaryFolder = TemporaryFolder()

    @Test
    fun clearingCachePreservesDownloadsAndTheirDirectory() {
        val cache = temporaryFolder.newFolder("cache")
        val codeCache = temporaryFolder.newFolder("code_cache")
        val downloads = File(cache, "downloads").apply { mkdirs() }
        val fragment = File(downloads, "active.mp4.part").apply { writeText("fragment") }
        val video = File(downloads, "saving.mp4").apply { writeText("video") }
        val disposable = File(cache, "images/preview").apply {
            parentFile!!.mkdirs()
            writeText("preview")
        }
        val compiled = File(codeCache, "compiled").apply { writeText("code") }

        FileUtils.clearCache(cache, codeCache)

        assertEquals("fragment", fragment.readText())
        assertEquals("video", video.readText())
        assertTrue(downloads.isDirectory)
        assertTrue(cache.isDirectory)
        assertTrue(codeCache.isDirectory)
        assertFalse(disposable.exists())
        assertFalse(compiled.exists())
    }

    @Test
    fun clearingCacheBeforeEnqueueAllowsNewDownloads() {
        val cache = temporaryFolder.newFolder("cache")
        val codeCache = temporaryFolder.newFolder("code_cache")
        FileUtils.clearCache(cache, codeCache)
        val downloads = File(cache, "downloads").apply { mkdirs() }
        val fragment = File(downloads, "new.mp4.part").apply { writeText("new") }
        FileUtils.clearCache(cache, codeCache)
        assertEquals("new", fragment.readText())
    }
}
