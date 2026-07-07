package com.chapman.wishweek

import com.chapman.wishweek.data.ChecklistLogic
import org.junit.Assert.assertEquals
import org.junit.Test

class ChecklistLogicTest {

    @Test
    fun `checked state persists for a normal list regardless of date`() {
        val checked = setOf(0, 2, 5)
        assertEquals(
            checked,
            ChecklistLogic.effectiveChecked(checked, resetDaily = false, storedDate = "2026-11-30", today = "2026-12-01")
        )
    }

    @Test
    fun `daily list keeps state within the same day`() {
        val checked = setOf(1, 3)
        assertEquals(
            checked,
            ChecklistLogic.effectiveChecked(checked, resetDaily = true, storedDate = "2026-12-01", today = "2026-12-01")
        )
    }

    @Test
    fun `daily list auto resets the next morning`() {
        val checked = setOf(1, 3)
        assertEquals(
            emptySet<Int>(),
            ChecklistLogic.effectiveChecked(checked, resetDaily = true, storedDate = "2026-12-01", today = "2026-12-02")
        )
    }

    @Test
    fun `daily list with no stored date reads as fresh`() {
        assertEquals(
            emptySet<Int>(),
            ChecklistLogic.effectiveChecked(setOf(4), resetDaily = true, storedDate = null, today = "2026-12-02")
        )
    }

    @Test
    fun `toggle adds then removes`() {
        val once = ChecklistLogic.toggle(emptySet(), 2)
        assertEquals(setOf(2), once)
        assertEquals(emptySet<Int>(), ChecklistLogic.toggle(once, 2))
    }

    @Test
    fun `encode decode round trips`() {
        val original = setOf(0, 7, 12)
        assertEquals(original, ChecklistLogic.decode(ChecklistLogic.encode(original)))
    }

    @Test
    fun `decode tolerates junk and null`() {
        assertEquals(setOf(3), ChecklistLogic.decode(setOf("3", "banana")))
        assertEquals(emptySet<Int>(), ChecklistLogic.decode(null))
    }
}
