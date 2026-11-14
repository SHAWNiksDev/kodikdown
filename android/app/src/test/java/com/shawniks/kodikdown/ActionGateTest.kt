package com.shawniks.kodikdown

import com.shawniks.kodikdown.ui.ActionGate
import org.junit.Assert.*
import org.junit.Test

class ActionGateTest {
    @Test fun rapidAlternatingActionsAreRejectedUntilCooldownEnds() {
        val gate = ActionGate(500)
        assertTrue(gate.accept(0))
        for (time in 1L..499L) assertFalse(gate.accept(time))
        assertTrue(gate.accept(500))
        assertFalse(gate.accept(999))
        assertTrue(gate.accept(1000))
    }
}
