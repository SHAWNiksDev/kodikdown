package com.shawniks.kodikdown.downloader

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.shawniks.kodikdown.KodikApp
import com.shawniks.kodikdown.MainActivity
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.DownloadItem
import com.shawniks.kodikdown.data.DownloadStatus
import com.shawniks.kodikdown.data.PreferencesManager
import kotlinx.coroutines.*
import java.util.Locale

class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    private var lastNotification: String? = null
    private var lastStage: String? = null

    companion object {
        const val CHANNEL_ID = "kodikdown_downloads"
        const val NOTIFICATION_ID = 1001
        fun start(context: Context) {
            val intent = Intent(context, DownloadService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent)
            else context.startService(intent)
        }
        fun stop(context: Context) { context.stopService(Intent(context, DownloadService::class.java)) }
    }

    private fun localizedContext(): Context {
        val lang = PreferencesManager(this).language
        if (lang == "auto") return this
        val config = android.content.res.Configuration(resources.configuration)
        config.setLocale(Locale.forLanguageTag(lang))
        return createConfigurationContext(config)
    }

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= 26) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, getString(R.string.notification_channel_name), NotificationManager.IMPORTANCE_LOW).apply {
                    setShowBadge(false)
                })
        }
        ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(emptyList()),
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
        wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "KodikDown:Downloads")
        wakeLock?.acquire(10 * 60 * 1000L)
        scope.launch {
            DownloadManager.items.collect { items ->
                val stage = items.filter { !it.isTerminal }.joinToString { "${it.id}:${it.status}:${it.waitingForNetwork}" }
                if (stage != lastStage) {
                    lastStage = stage
                    render(items)
                }
            }
        }
        scope.launch {
            while (isActive) {
                delay(1000)
                val items = DownloadManager.items.value
                if (items.any { !it.isTerminal } && wakeLock?.isHeld == false) wakeLock?.acquire(10 * 60 * 1000L)
                render(items)
            }
        }
    }

    private fun render(items: List<DownloadItem>) {
        val active = items.filter { !it.isTerminal }
        if (active.isEmpty()) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return
        }
        val signature = active.joinToString { "${it.id}:${it.status}:${it.waitingForNetwork}:${(it.progress * 100).toInt()}:${it.speedBytesPerSec / 1024}" } + PreferencesManager(this).language
        if (signature == lastNotification) return
        lastNotification = signature
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, buildNotification(active))
    }

    private fun buildNotification(items: List<DownloadItem>): Notification {
        val ctx = localizedContext()
        val first = items.firstOrNull { it.status == DownloadStatus.ASSEMBLING }
            ?: items.firstOrNull { it.status == DownloadStatus.DOWNLOADING } ?: items.firstOrNull()
        fun description(item: DownloadItem): String = when {
            item.status == DownloadStatus.ASSEMBLING -> ctx.getString(R.string.stage_processing)
            item.status == DownloadStatus.QUEUED -> ctx.getString(R.string.queued)
            item.waitingForNetwork -> ctx.getString(R.string.network_reconnecting)
            else -> {
                val percent = if (item.fragmentCount > 0 || item.totalBytes != null) "${(item.progress * 100).toInt()}%" else ctx.getString(R.string.status_downloading)
                val speed = if (item.speedBytesPerSec > 0) String.format(Locale.getDefault(), "%.1f MB/s", item.speedBytesPerSec / 1048576.0) else ""
                listOf(percent, speed).filter { it.isNotEmpty() }.joinToString(" • ")
            }
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val text = first?.let { description(it) } ?: ctx.getString(R.string.starting)
        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_download)
            .setContentTitle(first?.title ?: ctx.getString(R.string.app_name))
            .setContentText(text)
            .setSubText(ctx.getString(R.string.notification_active_count, items.size))
            .setStyle(NotificationCompat.BigTextStyle().bigText(items.take(4).joinToString("\n") { "${it.title}: ${description(it)}" }.ifEmpty { text }))
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).setSilent(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setShowWhen(false).setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setPriority(NotificationCompat.PRIORITY_LOW)
        val determinate = first?.status == DownloadStatus.DOWNLOADING &&
            (first.fragmentCount > 0 || first.totalBytes != null) && !first.waitingForNetwork
        builder.setProgress(100, ((first?.progress ?: 0f) * 100).toInt(), !determinate)
        return builder.build()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_NOT_STICKY
    }
    override fun onDestroy() {
        scope.cancel()
        if (wakeLock?.isHeld == true) wakeLock?.release()
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null
}
