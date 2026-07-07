package com.chapman.wishweek.data

import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** Where "today" falls relative to the trip. */
sealed class TripPhase {
    data class BeforeTrip(val daysUntil: Long) : TripPhase()

    /** dayIndex points into TripContent.days. dayNumber is 1-based for display. */
    data class DuringTrip(val dayIndex: Int, val dayNumber: Int) : TripPhase()

    object AfterTrip : TripPhase()
}

object DayResolver {

    fun parse(date: String): LocalDate = LocalDate.parse(date)

    /**
     * Resolve today's phase from the ordered day list. If today lands inside
     * the trip window but has no exact date entry (should not happen with a
     * contiguous itinerary), the most recent prior day is used.
     */
    fun resolve(today: LocalDate, dayDates: List<LocalDate>): TripPhase {
        if (dayDates.isEmpty()) return TripPhase.AfterTrip
        val first = dayDates.first()
        val last = dayDates.last()
        if (today.isBefore(first)) {
            return TripPhase.BeforeTrip(ChronoUnit.DAYS.between(today, first))
        }
        if (today.isAfter(last)) return TripPhase.AfterTrip
        var index = 0
        for (i in dayDates.indices) {
            if (!dayDates[i].isAfter(today)) index = i else break
        }
        return TripPhase.DuringTrip(dayIndex = index, dayNumber = index + 1)
    }

    fun resolve(today: LocalDate, content: TripContent): TripPhase =
        resolve(today, content.days.map { parse(it.date) })
}
