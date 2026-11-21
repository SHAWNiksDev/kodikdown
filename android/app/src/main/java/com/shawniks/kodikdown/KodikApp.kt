package com.shawniks.kodikdown

import android.app.Application
import android.app.LocaleManager
import android.os.Build
import android.os.LocaleList
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.downloader.DownloadManager

class KodikApp : Application() {
    companion object {
        lateinit var instance: KodikApp
            private set

        fun applyTheme(theme: String) {
            when (theme) {
                "light" -> AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_NO)
                "dark" -> AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_YES)
                else -> AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM)
            }
        }

        fun updateAppLocale(langCode: String) {
            if (Build.VERSION.SDK_INT >= 33) {
                instance.getSystemService(LocaleManager::class.java).applicationLocales =
                    if (langCode == "auto") LocaleList.getEmptyLocaleList()
                    else LocaleList.forLanguageTags(langCode)
                return
            }
            val locales = if (langCode == "auto") {
                LocaleListCompat.getEmptyLocaleList()
            } else {
                LocaleListCompat.forLanguageTags(langCode)
            }
            AppCompatDelegate.setApplicationLocales(locales)
        }
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        val prefs = PreferencesManager(this)
        applyTheme(prefs.theme)
        updateAppLocale(prefs.language)
        DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
    }
}
