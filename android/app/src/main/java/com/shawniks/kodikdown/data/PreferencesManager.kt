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
        const val KEY_DEFAULT_QUALITY = "default_quality"
        const val KEY_WIFI_ONLY = "wifi_only"
        const val KEY_AUTO_PASTE = "auto_paste"
        const val KEY_HAPTIC_FEEDBACK = "haptic_feedback"
        const val KEY_SWIPE_TO_DELETE = "swipe_to_delete"
        const val KEY_CONFIRM_CANCEL_DOWNLOAD = "confirm_cancel_download"
        const val KEY_CONFIRM_SWIPE_DELETE = "confirm_swipe_delete"

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

    var defaultQuality: String
        get() = prefs.getString(KEY_DEFAULT_QUALITY, "ask") ?: "ask"
        set(value) = prefs.edit().putString(KEY_DEFAULT_QUALITY, value).apply()

    var wifiOnly: Boolean
        get() = prefs.getBoolean(KEY_WIFI_ONLY, false)
        set(value) = prefs.edit().putBoolean(KEY_WIFI_ONLY, value).apply()

    var autoPaste: Boolean
        get() = prefs.getBoolean(KEY_AUTO_PASTE, false)
        set(value) = prefs.edit().putBoolean(KEY_AUTO_PASTE, value).apply()

    var hapticFeedback: Boolean
        get() = prefs.getBoolean(KEY_HAPTIC_FEEDBACK, true)
        set(value) = prefs.edit().putBoolean(KEY_HAPTIC_FEEDBACK, value).apply()

    var swipeToDelete: Boolean
        get() = prefs.getBoolean(KEY_SWIPE_TO_DELETE, true)
        set(value) = prefs.edit().putBoolean(KEY_SWIPE_TO_DELETE, value).apply()

    var confirmSwipeDelete: Boolean
        get() = prefs.getBoolean(KEY_CONFIRM_SWIPE_DELETE, false)
        set(value) = prefs.edit().putBoolean(KEY_CONFIRM_SWIPE_DELETE, value).apply()

    var confirmCancelDownload: Boolean
        get() = prefs.getBoolean(KEY_CONFIRM_CANCEL_DOWNLOAD, true)
        set(value) = prefs.edit().putBoolean(KEY_CONFIRM_CANCEL_DOWNLOAD, value).apply()

    fun getSettings(): AppSettings {
        return AppSettings(
            downloadDir = downloadDir,
            language = language,
            theme = theme,
            concurrentDownloads = concurrentDownloads,
            preferMp4 = preferMp4,
            defaultQuality = defaultQuality,
            wifiOnly = wifiOnly,
            autoPaste = autoPaste,
            hapticFeedback = hapticFeedback,
            swipeToDelete = swipeToDelete,
            confirmCancelDownload = confirmCancelDownload,
            confirmSwipeDelete = confirmSwipeDelete
        )
    }

    fun saveSettings(settings: AppSettings) {
        prefs.edit()
            .putString(KEY_DOWNLOAD_DIR, settings.downloadDir)
            .putString(KEY_LANGUAGE, settings.language)
            .putString(KEY_THEME, settings.theme)
            .putInt(KEY_CONCURRENT, settings.concurrentDownloads)
            .putBoolean(KEY_PREFER_MP4, settings.preferMp4)
            .putString(KEY_DEFAULT_QUALITY, settings.defaultQuality)
            .putBoolean(KEY_WIFI_ONLY, settings.wifiOnly)
            .putBoolean(KEY_AUTO_PASTE, settings.autoPaste)
            .putBoolean(KEY_HAPTIC_FEEDBACK, settings.hapticFeedback)
            .putBoolean(KEY_SWIPE_TO_DELETE, settings.swipeToDelete)
            .putBoolean(KEY_CONFIRM_SWIPE_DELETE, settings.confirmSwipeDelete)
            .putBoolean(KEY_CONFIRM_CANCEL_DOWNLOAD, settings.confirmCancelDownload)
            .apply()
    }

    fun resetToDefaults() {
        prefs.edit()
            .remove(KEY_DOWNLOAD_DIR)
            .remove(KEY_LANGUAGE)
            .remove(KEY_THEME)
            .remove(KEY_CONCURRENT)
            .remove(KEY_PREFER_MP4)
            .remove(KEY_DEFAULT_QUALITY)
            .remove(KEY_WIFI_ONLY)
            .remove(KEY_AUTO_PASTE)
            .remove(KEY_HAPTIC_FEEDBACK)
            .remove(KEY_SWIPE_TO_DELETE)
            .remove(KEY_CONFIRM_SWIPE_DELETE)
            .remove(KEY_CONFIRM_CANCEL_DOWNLOAD)
            .apply()
    }
}
