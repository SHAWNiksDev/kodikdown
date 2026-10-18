package com.shawniks.kodikdown

import android.app.Application
import android.content.Context
import android.content.res.Configuration
import androidx.appcompat.app.AppCompatDelegate
import com.shawniks.kodikdown.data.PreferencesManager
import com.shawniks.kodikdown.downloader.DownloadManager
import java.util.Locale

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

        fun applyLocale(context: Context, langCode: String): Context {
            if (langCode == "auto") {
                return context
            }
            val locale = Locale(langCode)
            Locale.setDefault(locale)
            val config = Configuration(context.resources.configuration)
            config.setLocale(locale)
            return context.createConfigurationContext(config)
        }
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        val prefs = PreferencesManager(this)
        applyTheme(prefs.theme)
        DownloadManager.maxConcurrentDownloads = prefs.concurrentDownloads
    }
}
