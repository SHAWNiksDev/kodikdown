package com.shawniks.kodikdown.ui

import android.content.Context
import android.util.AttributeSet
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout

/** Keep controls reachable in narrow windows and with large accessibility fonts. */
class AdaptiveRow @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : LinearLayout(context, attrs) {
    private data class Child(val view: View, val horizontal: LayoutParams, val vertical: LayoutParams,
        val minimumHeight: Int, val spacer: Boolean)
    private val children = mutableListOf<Child>()
    private var stackedMode: Boolean? = null

    override fun onFinishInflate() {
        super.onFinishInflate()
        val density = resources.displayMetrics.density
        for (index in 0 until childCount) {
            val child = getChildAt(index)
            val horizontal = LayoutParams(child.layoutParams as LayoutParams)
            val vertical = LayoutParams(horizontal).apply {
                width = ViewGroup.LayoutParams.MATCH_PARENT
                height = ViewGroup.LayoutParams.WRAP_CONTENT
                weight = 0f
                marginStart = 0
                marginEnd = 0
                if (index > 0) topMargin = maxOf(topMargin, (6 * density).toInt())
            }
            children.add(Child(child, horizontal, vertical, child.minimumHeight,
                child.javaClass == View::class.java && horizontal.width == 0 && horizontal.weight > 0))
        }
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val density = resources.displayMetrics.density
        val widthDp = MeasureSpec.getSize(widthMeasureSpec) / density
        val stacked = widthDp < 300 || (resources.configuration.fontScale >= 1.5f && widthDp < 600)
        if (stackedMode != stacked) {
            stackedMode = stacked
            orientation = if (stacked) VERTICAL else HORIZONTAL
            for (index in children.indices) {
                val child = children[index]
                child.view.layoutParams = if (stacked) child.vertical else child.horizontal
                child.view.minimumHeight = if (stacked && !child.spacer && child.horizontal.width != (80 * density).toInt())
                    maxOf(child.minimumHeight, (48 * density).toInt()) else child.minimumHeight
                if (child.spacer) child.view.visibility = if (stacked) View.GONE else View.VISIBLE
            }
        }
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
    }
}
