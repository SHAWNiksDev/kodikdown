package com.shawniks.kodikdown.ui

import android.content.Context
import android.util.AttributeSet
import android.widget.LinearLayout

/** Avoid stretching text and cards across the full width of a tablet. */
class ContentColumn @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : LinearLayout(context, attrs) {
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val maximum = (960 * resources.displayMetrics.density).toInt()
        val bounded = MeasureSpec.makeMeasureSpec(minOf(MeasureSpec.getSize(widthMeasureSpec), maximum), MeasureSpec.getMode(widthMeasureSpec))
        super.onMeasure(bounded, heightMeasureSpec)
    }
}
