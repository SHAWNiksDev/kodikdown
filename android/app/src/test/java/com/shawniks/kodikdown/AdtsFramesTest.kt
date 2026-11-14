package com.shawniks.kodikdown

import com.shawniks.kodikdown.downloader.AdtsFrames
import java.io.IOException
import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class AdtsFramesTest {
    private fun frame(crc: Boolean = false): ByteArray {
        val header = if (crc) 9 else 7
        val length = header + 4
        return byteArrayOf(0xff.toByte(), if (crc) 0xf0.toByte() else 0xf1.toByte(),
            0x50, 0x80.toByte(), (length shr 3).toByte(),
            (((length and 7) shl 5) or 0x1f).toByte(), 0xfc.toByte()) +
            (if (crc) byteArrayOf(0, 0) else byteArrayOf()) + byteArrayOf(1, 2, 3, 4)
    }

    @Test fun aggregatedSamplesBecomeSeparateRawAacFrames() {
        val data = frame() + frame() + frame()
        val buffer = ByteBuffer.wrap(data)
        val frames = AdtsFrames.split(buffer, data.size)
        assertTrue(AdtsFrames.isAdts(buffer, data.size))
        assertEquals(listOf(7, 18, 29), frames.map { it.offset })
        assertTrue(frames.all { it.size == 4 && it.sampleRate == 44100 })
        assertEquals(0, buffer.position())
    }

    @Test fun crcHeaderIsStrippedToo() {
        val data = frame(true)
        assertEquals(9, AdtsFrames.split(ByteBuffer.wrap(data), data.size).single().offset)
    }

    @Test fun truncatedAudioCannotBePublishedAsSuccess() {
        val data = frame().dropLast(1).toByteArray()
        assertThrows(IOException::class.java) { AdtsFrames.split(ByteBuffer.wrap(data), data.size) }
    }

    @Test fun ordinaryMp4AacSamplesAreNotAdts() {
        assertFalse(AdtsFrames.isAdts(ByteBuffer.wrap(byteArrayOf(0x21, 0x11, 0x45)), 3))
    }
}
