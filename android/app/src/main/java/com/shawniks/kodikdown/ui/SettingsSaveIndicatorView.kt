package com.shawniks.kodikdown.ui

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import android.view.animation.LinearInterpolator
import com.shawniks.kodikdown.R

/** One corner indicator. Repeated saves restart it instead of queuing toasts. */
class SettingsSaveIndicatorView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val bounds = RectF()
    private val check = Path()
    private var animator: ValueAnimator? = null
    private var angle = 0f
    private var saved = false
    private var active = false
    private var accent = 0xff3b7dff.toInt()
    private var success = 0xff22c55e.toInt()
    private val showSaved = Runnable {
        animator?.cancel()
        animator = null
        saved = true
        contentDescription = context.getString(R.string.settings_saved)
        invalidate()
    }
    private val hideIndicator = Runnable { finish() }

    fun pulse() {
        finish()
        val colors = context.obtainStyledAttributes(R.styleable.SettingsSaveIndicatorView)
        accent = colors.getColor(R.styleable.SettingsSaveIndicatorView_app_accent, accent)
        success = colors.getColor(R.styleable.SettingsSaveIndicatorView_app_success, success)
        colors.recycle()
        active = true
        contentDescription = context.getString(R.string.settings_saving)
        animator = ValueAnimator.ofFloat(0f, 360f).apply {
            duration = 650L
            repeatCount = ValueAnimator.INFINITE
            interpolator = LinearInterpolator()
            addUpdateListener { angle = it.animatedValue as Float; invalidate() }
            start()
        }
        postDelayed(showSaved, 400L)
        postDelayed(hideIndicator, 1300L)
        invalidate()
    }

    fun finish() {
        animator?.cancel()
        animator = null
        removeCallbacks(showSaved)
        removeCallbacks(hideIndicator)
        active = false
        saved = false
        contentDescription = null
        invalidate()
    }

    override fun onDetachedFromWindow() {
        finish()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (!active) return
        paint.color = if (saved) success else accent
        val size = minOf(width, height).toFloat()
        val left = (width - size) / 2f
        val top = (height - size) / 2f
        paint.strokeWidth = size * 0.079f
        if (saved) {
            check.reset()
            check.moveTo(left + size * 0.25f, top + size * 0.5f)
            check.lineTo(left + size * 0.43f, top + size * 0.68f)
            check.lineTo(left + size * 0.75f, top + size * 0.32f)
            canvas.drawPath(check, paint)
        } else {
            bounds.set(left + size * 0.21f, top + size * 0.21f,
                left + size * 0.79f, top + size * 0.79f)
            canvas.drawArc(bounds, angle, 265f, false, paint)
        }
    }
}
