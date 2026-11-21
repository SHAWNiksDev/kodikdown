package com.shawniks.kodikdown.downloader

import android.media.MediaCodec
import android.media.MediaFormat
import android.media.MediaMuxer
import androidx.annotation.OptIn
import androidx.media3.common.util.MediaFormatUtil
import androidx.media3.common.util.UnstableApi
import androidx.media3.muxer.Mp4Muxer
import androidx.media3.muxer.Muxer
import java.io.File
import java.nio.ByteBuffer

/** Preserve composition timestamps on Android 7.0 as well as newer devices. */
@OptIn(UnstableApi::class)
internal class Mp4Writer(file: File, compatibility: Boolean) {
    private val framework = if (compatibility) null else
        MediaMuxer(file.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
    private val legacy = if (compatibility) Mp4Muxer.Builder(file.outputStream()).build() else null
    private val tokens = mutableListOf<Muxer.TrackToken>()
    private var closed = false

    fun addTrack(format: MediaFormat): Int {
        framework?.let { return it.addTrack(format) }
        tokens.add(legacy!!.addTrack(MediaFormatUtil.createFormatFromMediaFormat(format)))
        return tokens.lastIndex
    }

    fun start() { framework?.start() }
    fun writeSampleData(track: Int, data: ByteBuffer, info: MediaCodec.BufferInfo) {
        if (framework != null) framework.writeSampleData(track, data, info)
        else {
            val sample = data.duplicate().apply { position(info.offset); limit(info.offset + info.size) }.slice()
            val sampleInfo = MediaCodec.BufferInfo().apply { set(0, info.size, info.presentationTimeUs, info.flags) }
            legacy!!.writeSampleData(tokens[track], sample, sampleInfo)
        }
    }

    fun stop() {
        framework?.stop() ?: legacy!!.close()
        closed = true
    }

    fun release() {
        if (framework != null) framework.release()
        else if (!closed) { closed = true; legacy!!.close() }
    }
}
