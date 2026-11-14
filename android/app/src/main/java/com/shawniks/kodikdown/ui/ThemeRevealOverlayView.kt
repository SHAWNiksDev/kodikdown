package com.shawniks.kodikdown.ui

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Rect
import android.graphics.Path
import android.os.Build
import android.util.AttributeSet
import android.view.View
import android.view.animation.AccelerateDecelerateInterpolator

class ThemeRevealOverlayView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var snapshot: Bitmap? = null
    private var cx: Float = 0f
    private var cy: Float = 0f
    private var currentRadius: Float = 0f
    private val clipPath = Path()
    private val destination = Rect()
    private var animator: ValueAnimator? = null

    fun startReveal(
        bitmap: Bitmap,
        originX: Float,
        originY: Float,
        duration: Long = 420L,
        onComplete: () -> Unit
    ) {
        animator?.removeAllListeners()
        animator?.cancel()
        snapshot = bitmap
        cx = originX
        cy = originY
        currentRadius = 0f
        alpha = 1f
        isClickable = true
        visibility = VISIBLE

        post {
            val w = width.toFloat().coerceAtLeast(1f)
            val h = height.toFloat().coerceAtLeast(1f)
            val maxRadius = kotlin.math.hypot(
                maxOf(cx, w - cx),
                maxOf(cy, h - cy)
            )

            animator = ValueAnimator.ofFloat(0f, maxRadius).apply {
                this.duration = duration
                interpolator = AccelerateDecelerateInterpolator()
                addUpdateListener { va ->
                    currentRadius = va.animatedValue as Float
                    invalidate()
                }
                addListener(object : AnimatorListenerAdapter() {
                    override fun onAnimationEnd(animation: Animator) {
                        visibility = GONE
                        snapshot = null
                        isClickable = false
                        onComplete()
                    }
                })
                start()
            }
        }
    }

    fun startFade(bitmap: Bitmap, onComplete: () -> Unit) {
        animator?.removeAllListeners()
        animator?.cancel()
        snapshot = bitmap
        currentRadius = 0f
        alpha = 1f
        visibility = VISIBLE
        isClickable = true
        post {
            animator = ValueAnimator.ofFloat(1f, 0f).apply {
                duration = 180L
                addUpdateListener { alpha = it.animatedValue as Float }
                addListener(object : AnimatorListenerAdapter() {
                    override fun onAnimationEnd(animation: Animator) {
                        visibility = GONE
                        snapshot = null
                        isClickable = false
                        alpha = 1f
                        onComplete()
                    }
                })
                start()
            }
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val bmp = snapshot ?: return
        if (bmp.isRecycled) return

        if (currentRadius <= 0f) {
            destination.set(0, 0, width, height)
            canvas.drawBitmap(bmp, null, destination, null)
            return
        }

        val saveCount = canvas.save()
        clipPath.reset()
        clipPath.addCircle(cx, cy, currentRadius, Path.Direction.CW)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            canvas.clipOutPath(clipPath)
        } else {
            @Suppress("DEPRECATION")
            canvas.clipPath(clipPath, android.graphics.Region.Op.DIFFERENCE)
        }

        destination.set(0, 0, width, height)
        canvas.drawBitmap(bmp, null, destination, null)
        canvas.restoreToCount(saveCount)
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        animator?.removeAllListeners()
        animator?.cancel()
        snapshot = null
    }
}
