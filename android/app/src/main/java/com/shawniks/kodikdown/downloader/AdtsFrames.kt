package com.shawniks.kodikdown.downloader

import java.io.IOException
import java.nio.ByteBuffer

/** MPEG-TS extractors can return several ADTS frames in one sample; MP4 needs raw AAC frames. */
object AdtsFrames {
    data class Frame(val offset: Int, val size: Int, val sampleRate: Int)
    private val sampleRates = intArrayOf(96000, 88200, 64000, 48000, 44100, 32000,
        24000, 22050, 16000, 12000, 11025, 8000, 7350)

    fun isAdts(buffer: ByteBuffer, size: Int): Boolean = size >= 2 &&
        (buffer.get(0).toInt() and 255) == 255 && (buffer.get(1).toInt() and 246) == 240

    fun split(buffer: ByteBuffer, size: Int): List<Frame> {
        val frames = mutableListOf<Frame>()
        var offset = 0
        fun byte(index: Int) = buffer.get(offset + index).toInt() and 255
        while (offset < size) {
            if (size - offset < 7 || byte(0) != 255 || byte(1) and 246 != 240)
                throw IOException("Incomplete ADTS audio frame")
            val header = if (byte(1) and 1 == 1) 7 else 9
            val length = ((byte(3) and 3) shl 11) or (byte(4) shl 3) or (byte(5) shr 5)
            val rate = sampleRates.getOrNull((byte(2) shr 2) and 15)
                ?: throw IOException("Unsupported AAC sample rate")
            if (byte(6) and 3 != 0) throw IOException("AAC with multiple raw blocks is unsupported")
            if (length <= header || offset + length > size)
                throw IOException("Truncated ADTS audio frame")
            frames.add(Frame(offset + header, length - header, rate))
            offset += length
        }
        return frames
    }
}
