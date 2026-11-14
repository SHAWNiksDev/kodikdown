package com.shawniks.kodikdown.downloader

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update

/** One shared gate survives settings changes; existing transfers keep their slots. */
class DownloadLimiter(limit: Int) {
    private data class State(val active: Int, val limit: Int)

    private val state = MutableStateFlow(State(0, limit.coerceIn(1, 5)))

    fun setLimit(limit: Int) {
        state.update { it.copy(limit = limit.coerceIn(1, 5)) }
    }

    suspend fun <T> withSlot(block: suspend () -> T): T {
        while (true) {
            val available = state.first { it.active < it.limit }
            if (state.compareAndSet(available, available.copy(active = available.active + 1))) break
        }
        try {
            return block()
        } finally {
            state.update { it.copy(active = it.active - 1) }
        }
    }
}
