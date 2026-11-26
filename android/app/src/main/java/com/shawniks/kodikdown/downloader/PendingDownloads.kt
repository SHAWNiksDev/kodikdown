package com.shawniks.kodikdown.downloader

import android.content.Context
import com.shawniks.kodikdown.data.DownloadItem
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.StreamVariant
import org.json.JSONArray
import org.json.JSONObject

internal data class PendingDownload(
    val item: DownloadItem,
    val directory: String,
    val translation: String?,
    val hls: String?,
    val variants: List<StreamVariant>,
    val referer: String?,
)

internal class PendingDownloads(context: Context) {
    private val settings = context.getSharedPreferences("download_queue", Context.MODE_PRIVATE)

    fun save(downloads: List<PendingDownload>): Boolean {
        val data = JSONArray()
        for (download in downloads) {
            val item = download.item
            data.put(JSONObject().apply {
                put("id", item.id)
                put("title", item.title)
                put("name", item.fileName)
                put("url", item.url)
                put("quality", item.quality)
                put("mp4", item.isMp4)
                put("status", item.status.name)
                put("error", item.errorMessage)
                put("source", item.sourceInput)
                put("retry", item.retryInput)
                put("series", item.series)
                put("directory", download.directory)
                put("voice", download.translation)
                put("hls", download.hls)
                put("referer", download.referer)
                put("variants", JSONArray().apply {
                    for (variant in download.variants) put(JSONObject().apply {
                        put("quality", variant.quality)
                        put("url", variant.url)
                        put("kind", variant.kind)
                        put("mp4", variant.directMp4)
                        put("referer", variant.referer)
                    })
                })
            })
        }
        return settings.edit().putString("entries", data.toString()).commit()
    }

    fun load(): List<PendingDownload> {
        val data = runCatching { JSONArray(settings.getString("entries", "[]")) }.getOrNull()
            ?: return emptyList()
        return (0 until data.length()).mapNotNull { index ->
            runCatching { decode(data.getJSONObject(index)) }.getOrNull()
        }.distinctBy { it.item.id }
    }

    private fun decode(data: JSONObject): PendingDownload {
        val id = data.getString("id")
        require(id.matches(Regex("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")))
        val status = when (data.optString("status")) {
            DownloadStatus.PAUSED.name -> DownloadStatus.PAUSED
            DownloadStatus.FAILED.name -> DownloadStatus.FAILED
            else -> DownloadStatus.QUEUED
        }
        val encoded = data.optJSONArray("variants") ?: JSONArray()
        val variants = (0 until encoded.length()).mapNotNull { index ->
            encoded.optJSONObject(index)?.let {
                StreamVariant(it.optInt("quality"), it.getString("url"), it.getString("kind"),
                    it.optional("mp4"), it.optional("referer"))
            }
        }
        val item = DownloadItem(id, data.getString("title"), data.getString("name"),
            data.getString("url"), data.optInt("quality"), data.optBoolean("mp4"),
            status = status, errorMessage = data.optional("error"), sourceInput = data.optional("source"),
            retryInput = data.optional("retry"), series = data.optional("series"))
        return PendingDownload(item, data.getString("directory"), data.optional("voice"),
            data.optional("hls"), variants, data.optional("referer"))
    }

    private fun JSONObject.optional(key: String): String? =
        optString(key).takeIf { !isNull(key) && it.isNotBlank() }
}
