package com.shawniks.kodikdown.ui

/** A shared monotonic cooldown, so alternating controls cannot bypass it. */
class ActionGate(private val intervalMs: Long) {
    private var lastAccepted: Long? = null
    fun accept(now: Long): Boolean {
        val previous = lastAccepted
        if (previous != null && now - previous < intervalMs) return false
        lastAccepted = now
        return true
    }
}
