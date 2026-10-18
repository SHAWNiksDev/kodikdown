package com.shawniks.kodikdown.ui

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.TextView
import com.shawniks.kodikdown.R

object ToastManager {
    fun show(container: ViewGroup, message: String, isError: Boolean = false) {
        val context = container.context
        val toastView = TextView(context).apply {
            text = message
            textSize = 13f
            setPadding(dpToPx(context, 16), dpToPx(context, 10), dpToPx(context, 16), dpToPx(context, 10))

            val bg = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dpToPx(context, 8).toFloat()
                setColor(getThemeColor(context, R.attr.app_surface))
                val borderColor = if (isError) {
                    getThemeColor(context, R.attr.app_danger)
                } else {
                    getThemeColor(context, R.attr.app_border_strong)
                }
                setStroke(dpToPx(context, 1), borderColor)
            }
            background = bg

            val textColor = if (isError) {
                getThemeColor(context, R.attr.app_danger)
            } else {
                getThemeColor(context, R.attr.app_text)
            }
            setTextColor(textColor)
            elevation = dpToPx(context, 6).toFloat()
        }

        val params = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply {
            gravity = Gravity.CENTER_HORIZONTAL
        }

        container.removeAllViews()
        container.addView(toastView, params)

        toastView.alpha = 0f
        toastView.translationY = dpToPx(context, 20).toFloat()
        toastView.animate()
            .alpha(1f)
            .translationY(0f)
            .setDuration(250)
            .start()

        toastView.postDelayed({
            if (toastView.parent != null) {
                toastView.animate()
                    .alpha(0f)
                    .translationY(dpToPx(context, 10).toFloat())
                    .setDuration(250)
                    .setListener(object : AnimatorListenerAdapter() {
                        override fun onAnimationEnd(animation: Animator) {
                            container.removeView(toastView)
                        }
                    })
                    .start()
            }
        }, 3000)
    }

    private fun dpToPx(context: Context, dp: Int): Int {
        val density = context.resources.displayMetrics.density
        return (dp * density).toInt()
    }

    private fun getThemeColor(context: Context, attrRes: Int): Int {
        val typedArray = context.obtainStyledAttributes(intArrayOf(attrRes))
        val color = typedArray.getColor(0, Color.WHITE)
        typedArray.recycle()
        return color
    }
}
