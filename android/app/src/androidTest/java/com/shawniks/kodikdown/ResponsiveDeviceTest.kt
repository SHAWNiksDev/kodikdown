package com.shawniks.kodikdown

import android.content.res.Configuration
import android.test.InstrumentationTestCase
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import com.shawniks.kodikdown.databinding.ActivityMainBinding
import com.shawniks.kodikdown.databinding.ItemHistoryBinding
import com.shawniks.kodikdown.databinding.ItemLibraryBinding
import com.shawniks.kodikdown.ui.AdaptiveRow
import java.util.Locale

@Suppress("DEPRECATION")
class ResponsiveDeviceTest : InstrumentationTestCase() {
    fun testPhoneTabletLandscapeAndLargeFonts() {
        var failure: Throwable? = null
        instrumentation.runOnMainSync {
            try {
                for ((width, height) in listOf(320 to 640, 411 to 800, 600 to 960, 1280 to 800, 640 to 320)) {
                    for (scale in listOf(1f, 2f)) for (language in listOf("ru", "en")) {
                        val label = "$width x $height font=$scale $language"
                        val config = Configuration(instrumentation.targetContext.resources.configuration).apply {
                            densityDpi = 160; screenWidthDp = width; screenHeightDp = height
                            smallestScreenWidthDp = minOf(width, height); fontScale = scale
                            orientation = if (width > height) Configuration.ORIENTATION_LANDSCAPE else Configuration.ORIENTATION_PORTRAIT
                            setLocale(Locale(language))
                        }
                        val context = ContextThemeWrapper(instrumentation.targetContext.createConfigurationContext(config), R.style.Theme_KodikDown)
                        val binding = ActivityMainBinding.inflate(LayoutInflater.from(context))
                        binding.viewDownloader.visibility = View.GONE
                        binding.viewSettings.visibility = View.VISIBLE
                        measure(binding.root, width, height)
                        for (control in listOf(binding.btnThemeAuto, binding.btnThemeLight, binding.btnLangAuto,
                            binding.btnLangEn, binding.switchConfirmCancelDownload, binding.btnSettingsGithub)) {
                            assertTrue("$label: inaccessible control ${control.id}", control.width > 0 && control.height >= 40)
                            if (control is TextView && control.layout != null) {
                                assertTrue("$label: clipped control ${control.text}",
                                    control.layout.height <= control.height - control.compoundPaddingTop - control.compoundPaddingBottom)
                            }
                        }
                        checkRows(binding.root, label)
                        assertTrue("$label: tablet column too wide", binding.mainContent.getChildAt(0).width <= 960)
                        val row = ItemHistoryBinding.inflate(LayoutInflater.from(context))
                        row.btnHistoryPlay.visibility = View.VISIBLE
                        measure(row.root, width - 32, 0)
                        checkRows(row.root, label)
                        val library = ItemLibraryBinding.inflate(LayoutInflater.from(context))
                        measure(library.root, width - 32, 0)
                        checkRows(library.root, label)
                        binding.viewSettings.visibility = View.GONE
                        binding.viewDownloader.visibility = View.VISIBLE
                        binding.cardResult.visibility = View.VISIBLE
                        binding.etUrl.setText("https://kodikplayer.com/video/42/abcdef0123456789/720p")
                        binding.btnClearUrl.visibility = View.VISIBLE
                        binding.etFileName.setText("Example video filename")
                        binding.tvResultTitle.text = "Example video with a longer title"
                        measure(binding.root, width, height)
                        checkRows(binding.root, label)
                        assertTrue("$label: URL input collapsed", binding.etUrl.width >= 80)
                        assertTrue("$label: URL input is too short", binding.etUrl.height >= 48)
                        assertEquals("$label: URL input does not fill its frame",
                            (binding.etUrl.parent as View).height, binding.etUrl.height)
                        assertTrue("$label: clear button is outside URL input",
                            binding.btnClearUrl.top >= binding.etUrl.top && binding.btnClearUrl.bottom <= binding.etUrl.bottom)
                        assertTrue("$label: filename input collapsed", binding.etFileName.width >= 80)
                    }
                }
            } catch (error: Throwable) { failure = error }
        }
        failure?.let { throw it }
    }

    private fun measure(view: View, width: Int, height: Int) {
        view.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(height, if (height == 0) View.MeasureSpec.UNSPECIFIED else View.MeasureSpec.EXACTLY))
        view.layout(0, 0, view.measuredWidth, view.measuredHeight)
    }

    private fun checkRows(view: View, label: String) {
        if (view.visibility == View.GONE) return
        if (view is ViewGroup) for (index in 0 until view.childCount) {
            val child = view.getChildAt(index)
            if (view is AdaptiveRow && child.visibility != View.GONE) {
                assertTrue("$label: row overflows (${child.javaClass.simpleName})", child.left >= 0 && child.right <= view.width)
            }
            checkRows(child, label)
        }
    }
}
