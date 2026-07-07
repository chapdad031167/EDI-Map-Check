package com.chapman.wishweek.data

import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

/**
 * Pure reminder scheduling rules, Android-free for unit testing. A reminder
 * fires only on dates inside the trip window; "parkDaysOnly" reminders skip
 * Village days (any day whose park is the Village itself).
 */
object ReminderLogic {

    const val TYPE_PARK_DAYS = "parkDaysOnly"
    const val TYPE_DAILY = "daily"

    /** A trip date plus whether it counts as a theme-park day. */
    data class TripDate(val date: LocalDate, val isParkDay: Boolean)

    fun isParkDay(park: String): Boolean =
        !park.contains("village", ignoreCase = true)

    fun tripDates(content: TripContent): List<TripDate> =
        content.days.map { TripDate(LocalDate.parse(it.date), isParkDay(it.park)) }

    fun parseTime(text: String): LocalTime? = try {
        val parts = text.trim().split(":")
        if (parts.size != 2) null
        else LocalTime.of(parts[0].toInt(), parts[1].toInt())
    } catch (_: Exception) {
        null
    }

    /**
     * The next moment this reminder should fire, strictly after [now], or
     * null if no eligible occurrence remains in the trip window.
     */
    fun nextFire(
        now: LocalDateTime,
        type: String,
        time: LocalTime,
        dates: List<TripDate>
    ): LocalDateTime? {
        for (d in dates) {
            if (type == TYPE_PARK_DAYS && !d.isParkDay) continue
            val candidate = LocalDateTime.of(d.date, time)
            if (candidate.isAfter(now)) return candidate
        }
        return null
    }

    /** True if [date] is an eligible fire date for this reminder type. */
    fun firesOn(date: LocalDate, type: String, dates: List<TripDate>): Boolean {
        val d = dates.find { it.date == date } ?: return false
        return type != TYPE_PARK_DAYS || d.isParkDay
    }
}
