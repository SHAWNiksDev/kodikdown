package com.shawniks.kodikdown.data

import android.content.Context
import android.content.SharedPreferences
import android.os.Environment
import java.io.File

class PreferencesManager(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("kodikdown_prefs", Context.MODE_PRIVATE)

    companion object {
        const val KEY_DOWNLOAD_DIR = "download_dir"
        const val KEY_LANGUAGE = "language"
        const val KEY_THEME = "theme"
        const val KEY_CONCURRENT = "concurrent_downloads"
        const val KEY_PREFER_MP4 = "prefer_mp4"

        fun defaultDownloadDir(): String {
            val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            val appFolder = File(downloads, "KodikDown")
            return appFolder.absolutePath
        }
    }

    var downloadDir: String
        get() = prefs.getString(KEY_DOWNLOAD_DIR, null) ?: defaultDownloadDir()
        set(value) = prefs.edit().putString(KEY_DOWNLOAD_DIR, value).apply()

    var language: String
        get() = prefs.getString(KEY_LANGUAGE, "auto") ?: "auto"
        set(value) = prefs.edit().putString(KEY_LANGUAGE, value).apply()

    var theme: String
        get() = prefs.getString(KEY_THEME, "auto") ?: "auto"
        set(value) = prefs.edit().putString(KEY_THEME, value).apply()

    var concurrentDownloads: Int
        get() = prefs.getInt(KEY_CONCURRENT, 3)
        set(value) = prefs.edit().putInt(KEY_CONCURRENT, value.coerceIn(1, 5)).apply()

    var preferMp4: Boolean
        get() = prefs.getBoolean(KEY_PREFER_MP4, false)
        set(value) = prefs.edit().putBoolean(KEY_PREFER_MP4, value).apply()

    fun getSettings(): AppSettings {
        return AppSettings(
            downloadDir = downloadDir,
            language = language,
            theme = theme,
            concurrentDownloads = concurrentDownloads,
            preferMp4 = preferMp4
        )
    }

    fun saveSettings(settings: AppSettings) {
        prefs.edit()
            .putString(KEY_DOWNLOAD_DIR, settings.downloadDir)
            .putString(KEY_LANGUAGE, settings.language)
            .putString(KEY_THEME, settings.theme)
            .putInt(KEY_CONCURRENT, settings.concurrentDownloads)
            .putBoolean(KEY_PREFER_MP4, settings.preferMp4)
            .apply()
    }
}
