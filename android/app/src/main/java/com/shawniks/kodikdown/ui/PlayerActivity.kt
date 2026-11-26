package com.shawniks.kodikdown.ui

import android.content.Context
import android.content.Intent
import android.media.MediaPlayer
import android.net.Uri
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.SeekBar
import androidx.activity.addCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.isVisible
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import com.shawniks.kodikdown.R
import com.shawniks.kodikdown.data.MediaFiles
import com.shawniks.kodikdown.databinding.ActivityPlayerBinding
import com.shawniks.kodikdown.util.FileUtils
import java.io.File
import java.util.Locale
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class PlayerActivity : AppCompatActivity() {
    private lateinit var binding: ActivityPlayerBinding
    private val positions by lazy { getSharedPreferences("playback_positions", MODE_PRIVATE) }
    private val rates = listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 1.75f, 2f)
    private var media: MediaPlayer? = null
    private var completed = false
    private var fullscreen = false
    private var dragging = false
    private var playbackKey = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val source = intent.getStringExtra("source")
        if (source.isNullOrBlank()) {
            finish()
            return
        }
        val file = File(source)
        val uri = if (source.startsWith("content://")) Uri.parse(source) else Uri.fromFile(file)
        playbackKey = if (uri.scheme == "file") "$source|${file.length()}|${file.lastModified()}" else source
        binding = ActivityPlayerBinding.inflate(layoutInflater)
        setContentView(binding.root)
        binding.playerTitle.text = intent.getStringExtra("title") ?: file.name
        binding.playerClose.setOnClickListener { finish() }
        binding.playerExternal.setOnClickListener {
            binding.video.pause()
            renderProgress()
            FileUtils.openFile(this, source)
        }
        binding.playerFullscreen.setOnClickListener { setFullscreen(!fullscreen) }
        onBackPressedDispatcher.addCallback(this) {
            if (fullscreen) setFullscreen(false) else finish()
        }
        binding.playerToggle.setOnClickListener {
            if (binding.video.isPlaying) {
                binding.video.pause()
            } else {
                if (completed) binding.video.seekTo(0)
                completed = false
                binding.video.start()
                applySpeed()
            }
            renderProgress()
        }
        binding.playerSpeed.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
            rates.map { "${it.toString().removeSuffix(".0")}×" })
        binding.playerSpeed.setSelection(2)
        binding.playerSpeed.onItemSelectedListener = object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: android.widget.AdapterView<*>?) = Unit
            override fun onItemSelected(parent: android.widget.AdapterView<*>?, view: android.view.View?,
                position: Int, id: Long) {
                if (binding.video.isPlaying) applySpeed()
            }
        }
        binding.playerPosition.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onStartTrackingTouch(bar: SeekBar) { dragging = true }
            override fun onStopTrackingTouch(bar: SeekBar) {
                dragging = false
                binding.video.seekTo(bar.progress)
                completed = false
            }
            override fun onProgressChanged(bar: SeekBar, value: Int, fromUser: Boolean) {
                if (fromUser) {
                    if (!dragging) {
                        binding.video.seekTo(value)
                        completed = false
                    }
                    renderTime(value)
                }
            }
        })
        binding.video.setOnPreparedListener { player ->
            media = player
            binding.playerToggle.isEnabled = true
            binding.playerPosition.isEnabled = player.duration > 0
            binding.playerPosition.max = player.duration.coerceAtLeast(0)
            val lastPosition = positions.getInt(playbackKey, 0)
            if (lastPosition in 1 until (player.duration - 1000)) binding.video.seekTo(lastPosition)
            if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) binding.video.start()
            renderProgress()
        }
        binding.video.setOnCompletionListener {
            completed = true
            positions.edit().remove(playbackKey).apply()
            renderProgress()
        }
        binding.video.setOnErrorListener { _, _, _ ->
            media = null
            binding.playerError.isVisible = true
            binding.playerToggle.isEnabled = false
            binding.playerPosition.isEnabled = false
            true
        }
        binding.video.setVideoURI(uri)
        lifecycleScope.launch {
            while (isActive) {
                if (media != null) renderProgress()
                delay(300)
            }
        }
        setFullscreen(savedInstanceState?.getBoolean("fullscreen") == true)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("fullscreen", fullscreen)
        super.onSaveInstanceState(outState)
    }

    override fun onPause() {
        if (::binding.isInitialized && media != null) {
            val position = binding.video.currentPosition
            if (!completed && position in 1000 until (binding.video.duration - 1000)) {
                positions.edit().putInt(playbackKey, position).apply()
            } else if (completed || position > 0) {
                positions.edit().remove(playbackKey).apply()
            }
            binding.video.pause()
        }
        super.onPause()
    }

    override fun onDestroy() {
        if (::binding.isInitialized) binding.video.stopPlayback()
        media = null
        super.onDestroy()
    }

    private fun applySpeed() {
        val player = media ?: return
        val speed = rates.getOrNull(binding.playerSpeed.selectedItemPosition) ?: return
        try {
            player.playbackParams = player.playbackParams.setSpeed(speed)
        } catch (_: IllegalArgumentException) {
            binding.playerSpeed.setSelection(2)
        } catch (_: IllegalStateException) {
            // The decoder can release its surface while the activity is closing.
        }
    }

    private fun renderProgress() {
        if (!dragging) {
            val position = binding.video.currentPosition
            binding.playerPosition.progress = position
            renderTime(position)
        }
        binding.playerToggle.setText(if (binding.video.isPlaying) R.string.pause_download else R.string.play)
    }

    private fun renderTime(position: Int) {
        binding.playerTime.text = getString(R.string.player_time, time(position),
            time(binding.video.duration.coerceAtLeast(0)))
    }

    private fun time(milliseconds: Int): String {
        val seconds = milliseconds / 1000
        return String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60)
    }

    private fun setFullscreen(enabled: Boolean) {
        fullscreen = enabled
        binding.playerHeader.isVisible = !enabled
        binding.playerFullscreen.setText(if (enabled) R.string.player_exit_fullscreen else R.string.player_fullscreen)
        val insets = WindowInsetsControllerCompat(window, binding.root)
        insets.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        if (enabled) insets.hide(WindowInsetsCompat.Type.systemBars())
        else insets.show(WindowInsetsCompat.Type.systemBars())
    }

    companion object {
        fun open(context: Context, source: String, title: String = "") {
            MediaFiles.withAvailable(context, source) {
                context.startActivity(Intent(context, PlayerActivity::class.java).apply {
                    putExtra("source", source)
                    putExtra("title", title.ifBlank { File(source).name })
                })
            }
        }
    }
}
