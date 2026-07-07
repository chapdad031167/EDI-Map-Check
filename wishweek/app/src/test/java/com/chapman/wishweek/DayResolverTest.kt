package com.chapman.wishweek

import com.chapman.wishweek.data.DayResolver
import com.chapman.wishweek.data.TripPhase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class DayResolverTest {

    private val tripDays = listOf(
        "2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03",
        "2026-12-04", "2026-12-05", "2026-12-06"
    ).map { LocalDate.parse(it) }

    @Test
    fun `before the trip returns a countdown`() {
        val phase = DayResolver.resolve(LocalDate.parse("2026-11-20"), tripDays)
        assertTrue(phase is TripPhase.BeforeTrip)
        assertEquals(10L, (phase as TripPhase.BeforeTrip).daysUntil)
    }

    @Test
    fun `day before departure counts one day`() {
        val phase = DayResolver.resolve(LocalDate.parse("2026-11-29"), tripDays)
        assertEquals(1L, (phase as TripPhase.BeforeTrip).daysUntil)
    }

    @Test
    fun `first trip day resolves to day one`() {
        val phase = DayResolver.resolve(LocalDate.parse("2026-11-30"), tripDays)
        val during = phase as TripPhase.DuringTrip
        assertEquals(0, during.dayIndex)
        assertEquals(1, during.dayNumber)
    }

    @Test
    fun `dino day resolves to day three`() {
        val phase = DayResolver.resolve(LocalDate.parse("2026-12-02"), tripDays)
        val during = phase as TripPhase.DuringTrip
        assertEquals(2, during.dayIndex)
        assertEquals(3, during.dayNumber)
    }

    @Test
    fun `last trip day resolves to day seven`() {
        val phase = DayResolver.resolve(LocalDate.parse("2026-12-06"), tripDays)
        val during = phase as TripPhase.DuringTrip
        assertEquals(6, during.dayIndex)
        assertEquals(7, during.dayNumber)
    }

    @Test
    fun `after the trip is after`() {
        val phase = DayResolver.resolve(LocalDate.parse("2026-12-07"), tripDays)
        assertTrue(phase is TripPhase.AfterTrip)
    }

    @Test
    fun `gap inside the window falls back to most recent prior day`() {
        val sparse = listOf("2026-11-30", "2026-12-02").map { LocalDate.parse(it) }
        val phase = DayResolver.resolve(LocalDate.parse("2026-12-01"), sparse)
        assertEquals(0, (phase as TripPhase.DuringTrip).dayIndex)
    }

    @Test
    fun `empty day list does not crash`() {
        assertTrue(DayResolver.resolve(LocalDate.parse("2026-12-01"), emptyList()) is TripPhase.AfterTrip)
    }
}
