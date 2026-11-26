package com.shawniks.kodikdown.data

import android.content.Context
import org.json.JSONObject

data class FavoriteSeries(
    val url: String,
    val title: String,
    val player: String,
    val voice: String,
    val quality: Int,
    val grouped: Boolean,
    val preferMp4: Boolean,
)

class Favorites(context: Context) {
    private val settings = context.getSharedPreferences("favorite_series", Context.MODE_PRIVATE)

    fun entries(): List<FavoriteSeries> = settings.all.mapNotNull { (url, data) ->
        runCatching {
            val json = JSONObject(data as String)
            FavoriteSeries(url, json.getString("title"), json.getString("player"), json.getString("voice"),
                json.getInt("quality"), json.getBoolean("grouped"), json.getBoolean("mp4"))
        }.getOrNull()
    }.sortedBy { it.title.lowercase() }

    fun save(item: FavoriteSeries) {
        val data = JSONObject().put("title", item.title).put("player", item.player).put("voice", item.voice)
            .put("quality", item.quality).put("grouped", item.grouped).put("mp4", item.preferMp4)
        settings.edit().putString(item.url, data.toString()).apply()
    }

    fun remove(item: FavoriteSeries) {
        settings.edit().remove(item.url).apply()
    }
}
