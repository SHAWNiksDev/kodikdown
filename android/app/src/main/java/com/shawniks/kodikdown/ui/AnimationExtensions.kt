package com.shawniks.kodikdown.ui

import android.annotation.SuppressLint
import android.view.MotionEvent
import android.view.View
import android.view.animation.DecelerateInterpolator
import android.view.animation.OvershootInterpolator

object AnimationExtensions {

    @SuppressLint("ClickableViewAccessibility")
    fun View.applyPressEffect(scaleDown: Float = 0.93f) {
        setOnTouchListener { v, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    v.animate()
                        .scaleX(scaleDown)
                        .scaleY(scaleDown)
                        .setDuration(100)
                        .setInterpolator(DecelerateInterpolator())
                        .start()
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    v.animate()
                        .scaleX(1.0f)
                        .scaleY(1.0f)
                        .setDuration(180)
                        .setInterpolator(OvershootInterpolator(3.0f))
                        .start()
                }
            }
            false
        }
    }

    fun View.popBounce(fromScale: Float = 0.85f, duration: Long = 240) {
        scaleX = fromScale
        scaleY = fromScale
        alpha = 0.4f
        animate()
            .scaleX(1.0f)
            .scaleY(1.0f)
            .alpha(1.0f)
            .setDuration(duration)
            .setInterpolator(OvershootInterpolator(2.5f))
            .start()
    }
}
