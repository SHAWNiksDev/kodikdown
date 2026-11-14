package com.shawniks.kodikdown.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.RecyclerView
import com.shawniks.kodikdown.R

class SwipeToDeleteCallback(
    context: Context,
    private val canSwipe: (Int) -> Boolean = { true },
    private val onSwipedAction: (position: Int, direction: Int) -> Unit
) : ItemTouchHelper.SimpleCallback(0, ItemTouchHelper.LEFT or ItemTouchHelper.RIGHT) {

    private val deleteIcon = ContextCompat.getDrawable(context, R.drawable.ic_trash)
    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#E53935") // Red
    }
    private val cornerRadius = 12f * context.resources.displayMetrics.density

    override fun getSwipeDirs(recyclerView: RecyclerView, viewHolder: RecyclerView.ViewHolder): Int {
        val position = @Suppress("DEPRECATION") viewHolder.adapterPosition
        return if (position != RecyclerView.NO_POSITION && canSwipe(position))
            super.getSwipeDirs(recyclerView, viewHolder) else 0
    }

    override fun getSwipeThreshold(viewHolder: RecyclerView.ViewHolder): Float = 0.28f
    override fun getSwipeEscapeVelocity(defaultValue: Float): Float = defaultValue * 0.65f
    override fun getAnimationDuration(recyclerView: RecyclerView, animationType: Int,
        animateDx: Float, animateDy: Float): Long = 180L

    override fun onMove(
        recyclerView: RecyclerView,
        viewHolder: RecyclerView.ViewHolder,
        target: RecyclerView.ViewHolder
    ): Boolean = false

    override fun onSwiped(viewHolder: RecyclerView.ViewHolder, direction: Int) {
        val pos = @Suppress("DEPRECATION") viewHolder.adapterPosition
        if (pos != RecyclerView.NO_POSITION) {
            onSwipedAction(pos, direction)
        }
    }

    override fun onChildDraw(
        c: Canvas,
        recyclerView: RecyclerView,
        viewHolder: RecyclerView.ViewHolder,
        dX: Float,
        dY: Float,
        actionState: Int,
        isCurrentlyActive: Boolean
    ) {
        val itemView = viewHolder.itemView
        val icon = deleteIcon

        if (dX != 0f && icon != null) {
            val iconMargin = (itemView.height - icon.intrinsicHeight) / 2
            val iconTop = itemView.top + iconMargin
            val iconBottom = iconTop + icon.intrinsicHeight

            if (dX > 0) { // Swiping Right
                val rect = RectF(
                    itemView.left.toFloat(),
                    itemView.top.toFloat(),
                    itemView.left + dX,
                    itemView.bottom.toFloat()
                )
                c.drawRoundRect(rect, cornerRadius, cornerRadius, bgPaint)

                val iconLeft = itemView.left + iconMargin
                val iconRight = iconLeft + icon.intrinsicWidth
                icon.setBounds(iconLeft, iconTop, iconRight, iconBottom)
                icon.draw(c)
            } else { // Swiping Left
                val rect = RectF(
                    itemView.right + dX,
                    itemView.top.toFloat(),
                    itemView.right.toFloat(),
                    itemView.bottom.toFloat()
                )
                c.drawRoundRect(rect, cornerRadius, cornerRadius, bgPaint)

                val iconRight = itemView.right - iconMargin
                val iconLeft = iconRight - icon.intrinsicWidth
                icon.setBounds(iconLeft, iconTop, iconRight, iconBottom)
                icon.draw(c)
            }
        }

        super.onChildDraw(c, recyclerView, viewHolder, dX, dY, actionState, isCurrentlyActive)
    }
}
