package com.shawniks.kodikdown.ui

import android.graphics.Bitmap

object ThemeRevealHelper {
    var snapshot: Bitmap? = null
    var originX: Int = 0
    var originY: Int = 0
    var isTransitioning: Boolean = false

    fun clear() {
        // Never call snapshot?.recycle() because HardwareRenderer / Views might still
        // be completing a draw call on this frame. Simply drop the reference for GC.
        snapshot = null
        isTransitioning = false
    }
}
