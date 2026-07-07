package com.chapman.wishweek

import com.chapman.wishweek.data.ReminderLogic
import com.chapman.wishweek.data.ReminderLogic.TripDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

class ReminderLogicTest {

    // Trip shape from the real content: Village days are Nov 30, Dec 3, Dec 6.
    private val dates = listOf(
        TripDate(LocalDate.parse("2026-11-30"), isParkDay = false),
        TripDate(LocalDate.parse("2026-12-01"), isParkDay = true),
        TripDate(LocalDate.parse("2026-12-02"), isParkDay = true),
        TripDate(LocalDate.parse("2026-12-03"), isParkDay = false),
        TripDate(LocalDate.parse("2026-12-04"), isParkDay = true),
        TripDate(LocalDate.parse("2026-12-05"), isParkDay = true),
        TripDate(LocalDate.parse("2026-12-06"), isParkDay = false)
    )
    private val lunch = LocalTime.of(11, 30)
    private val tuckIn = LocalTime.of(19, 30)

    @Test
    fun `park day detection is Village-based`() {
        assertFalse(ReminderLogic.isParkDay("Give Kids the World Village"))
        assertTrue(ReminderLogic.isParkDay("Magic Kingdom"))
        assertTrue(ReminderLogic.isParkDay("Islands of Adventure"))
    }

    @Test
    fun `before the trip nothing fires until the window opens`() {
        val now = LocalDateTime.parse("2026-11-20T08:00:00")
        // Daily tuck-in first fires on arrival night.
        assertEquals(
            LocalDateTime.parse("2026-11-30T19:30:00"),
            ReminderLogic.nextFire(now, ReminderLogic.TYPE_DAILY, tuckIn, dates)
        )
        // parkDaysOnly lunch skips the Village travel day and waits for MK day.
        assertEquals(
            LocalDateTime.parse("2026-12-01T11:30:00"),
            ReminderLogic.nextFire(now, ReminderLogic.TYPE_PARK_DAYS, lunch, dates)
        )
    }

    @Test
    fun `mid trip after today's time has passed it moves to the next eligible day`() {
        // Dec 2, 12:00: lunch already fired; Dec 3 is a Village day, so Dec 4.
        val now = LocalDateTime.parse("2026-12-02T12:00:00")
        assertEquals(
            LocalDateTime.parse("2026-12-04T11:30:00"),
            ReminderLogic.nextFire(now, ReminderLogic.TYPE_PARK_DAYS, lunch, dates)
        )
        // Daily tuck-in still fires tonight.
        assertEquals(
            LocalDateTime.parse("2026-12-02T19:30:00"),
            ReminderLogic.nextFire(now, ReminderLogic.TYPE_DAILY, tuckIn, dates)
        )
    }

    @Test
    fun `exactly at fire time schedules the next occurrence, not this instant`() {
        val now = LocalDateTime.parse("2026-12-01T11:30:00")
        assertEquals(
            LocalDateTime.parse("2026-12-02T11:30:00"),
            ReminderLogic.nextFire(now, ReminderLogic.TYPE_PARK_DAYS, lunch, dates)
        )
    }

    @Test
    fun `after the last eligible occurrence nothing fires ever again`() {
        // Last park day is Dec 5; after its lunch there is no park lunch left.
        val now = LocalDateTime.parse("2026-12-05T12:00:00")
        assertNull(ReminderLogic.nextFire(now, ReminderLogic.TYPE_PARK_DAYS, lunch, dates))
        // Daily tuck-in still has Dec 5 and Dec 6 left.
        assertEquals(
            LocalDateTime.parse("2026-12-05T19:30:00"),
            ReminderLogic.nextFire(now, ReminderLogic.TYPE_DAILY, tuckIn, dates)
        )
        // And after the trip, nothing at all.
        val afterTrip = LocalDateTime.parse("2026-12-06T20:00:00")
        assertNull(ReminderLogic.nextFire(afterTrip, ReminderLogic.TYPE_DAILY, tuckIn, dates))
    }

    @Test
    fun `firesOn respects type and window`() {
        assertTrue(ReminderLogic.firesOn(LocalDate.parse("2026-12-01"), ReminderLogic.TYPE_PARK_DAYS, dates))
        assertFalse(ReminderLogic.firesOn(LocalDate.parse("2026-11-30"), ReminderLogic.TYPE_PARK_DAYS, dates))
        assertTrue(ReminderLogic.firesOn(LocalDate.parse("2026-11-30"), ReminderLogic.TYPE_DAILY, dates))
        assertFalse(ReminderLogic.firesOn(LocalDate.parse("2026-12-25"), ReminderLogic.TYPE_DAILY, dates))
    }

    @Test
    fun `time parsing accepts HH-mm and rejects junk`() {
        assertEquals(LocalTime.of(14, 0), ReminderLogic.parseTime("14:00"))
        assertEquals(LocalTime.of(9, 5), ReminderLogic.parseTime("9:05"))
        assertNull(ReminderLogic.parseTime("noonish"))
        assertNull(ReminderLogic.parseTime("25:00"))
        assertNull(ReminderLogic.parseTime("14"))
    }
}
