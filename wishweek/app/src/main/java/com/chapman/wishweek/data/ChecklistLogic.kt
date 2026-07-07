package com.chapman.wishweek.data

/**
 * Pure checklist state rules, kept free of Android types so they are unit
 * testable. Persistence stores, per list: the set of checked item indices and
 * the date (ISO yyyy-MM-dd) they were last touched. Daily lists ignore stale
 * state: if the stored date is not today, the list reads as fresh.
 */
object ChecklistLogic {

    fun effectiveChecked(
        stored: Set<Int>,
        resetDaily: Boolean,
        storedDate: String?,
        today: String
    ): Set<Int> = if (resetDaily && storedDate != today) emptySet() else stored

    fun toggle(current: Set<Int>, index: Int): Set<Int> =
        if (index in current) current - index else current + index

    fun encode(checked: Set<Int>): Set<String> = checked.map { it.toString() }.toSet()

    fun decode(raw: Set<String>?): Set<Int> =
        raw?.mapNotNull { it.toIntOrNull() }?.toSet() ?: emptySet()
}
