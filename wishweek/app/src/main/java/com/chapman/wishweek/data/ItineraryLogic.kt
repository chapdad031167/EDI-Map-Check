package com.chapman.wishweek.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * Editable itinerary engine. The bundled JSON is the immutable base layer;
 * user edits live as one DayEdit override per date (persisted in Room as
 * JSON) and the renderer merges the two, same pattern as placeholder
 * overrides. All logic here is pure and unit tested.
 *
 * Rules:
 * - Original events carry origIndex pointing into the base day; added events
 *   have origIndex == null.
 * - Deleting an original event is a soft delete (kept, hidden, restorable);
 *   deleting an added event removes it outright.
 * - "Restore day" drops the override; global restore drops them all.
 * - An event is "modified" if it differs from its base event; a day is
 *   modified if any event drifted or day fields changed.
 */
@Serializable
data class EditedEvent(
    val id: String,
    val origIndex: Int? = null,
    val deleted: Boolean = false,
    val time: String? = null,
    val title: String = "",
    val location: String? = null,
    val notes: String? = null,
    val mustDo: Boolean = false,
    val heightMin: Int? = null,
    val heightMax: Int? = null
) {
    fun toEvent() = TripEvent(
        time = time,
        title = title,
        location = location,
        notes = notes,
        mustDo = mustDo,
        heightMin = heightMin,
        heightMax = heightMax
    )
}

@Serializable
data class DayEdit(
    val date: String,
    val title: String,
    val emoji: String,
    val park: String,
    val events: List<EditedEvent>
)

/** One display row after merging: the event plus its drift status. */
data class DisplayEvent(
    val id: String,
    val event: TripEvent,
    val added: Boolean,
    val modified: Boolean
)

data class DisplayDay(
    val date: String,
    val title: String,
    val emoji: String,
    val park: String,
    val events: List<DisplayEvent>,
    val planB: String?,
    val dayModified: Boolean
)

object ItineraryLogic {

    private val json = Json { ignoreUnknownKeys = true }

    fun eventId(date: String, index: Int): String = "$date#$index"

    private fun fromEvent(id: String, origIndex: Int?, e: TripEvent) = EditedEvent(
        id = id,
        origIndex = origIndex,
        time = e.time,
        title = e.title,
        location = e.location,
        notes = e.notes,
        mustDo = e.mustDo,
        heightMin = e.heightMin,
        heightMax = e.heightMax
    )

    /** Seed an override from the base day (identity edit, nothing modified yet). */
    fun seed(base: TripDay): DayEdit = DayEdit(
        date = base.date,
        title = base.title,
        emoji = base.emoji,
        park = base.park,
        events = base.events.mapIndexed { i, e -> fromEvent(eventId(base.date, i), i, e) }
    )

    private fun sameAsBase(edited: EditedEvent, base: TripEvent): Boolean =
        edited.time == base.time &&
            edited.title == base.title &&
            edited.location == base.location &&
            edited.notes == base.notes &&
            edited.mustDo == base.mustDo &&
            edited.heightMin == base.heightMin &&
            edited.heightMax == base.heightMax

    fun isEventModified(edited: EditedEvent, baseDay: TripDay): Boolean {
        val orig = edited.origIndex?.let { baseDay.events.getOrNull(it) } ?: return true
        return !sameAsBase(edited, orig)
    }

    /** Merge base + optional override into what the UI renders. */
    fun display(base: TripDay, edit: DayEdit?): DisplayDay {
        if (edit == null) {
            return DisplayDay(
                date = base.date,
                title = base.title,
                emoji = base.emoji,
                park = base.park,
                events = base.events.mapIndexed { i, e ->
                    DisplayEvent(eventId(base.date, i), e, added = false, modified = false)
                },
                planB = base.planB,
                dayModified = false
            )
        }
        val visible = edit.events.filter { !it.deleted }
        val events = visible.map { ee ->
            DisplayEvent(
                id = ee.id,
                event = ee.toEvent(),
                added = ee.origIndex == null,
                modified = isEventModified(ee, base)
            )
        }
        val fieldsChanged = edit.title != base.title || edit.emoji != base.emoji || edit.park != base.park
        val eventsChanged = edit.events.any { it.deleted && it.origIndex != null } ||
            events.any { it.modified } ||
            visible.map { it.origIndex } != base.events.indices.toList()
        return DisplayDay(
            date = base.date,
            title = edit.title,
            emoji = edit.emoji,
            park = edit.park,
            events = events,
            planB = base.planB,
            dayModified = fieldsChanged || eventsChanged
        )
    }

    /** True if the override is byte-for-byte the original plan (safe to drop). */
    fun isIdentity(edit: DayEdit, base: TripDay): Boolean =
        !display(base, edit).dayModified

    fun updateEvent(edit: DayEdit, updated: EditedEvent): DayEdit =
        edit.copy(events = edit.events.map { if (it.id == updated.id) updated else it })

    fun addEvent(edit: DayEdit, event: EditedEvent, afterId: String? = null): DayEdit {
        val idx = edit.events.indexOfFirst { it.id == afterId }
        val list = edit.events.toMutableList()
        if (idx >= 0) list.add(idx + 1, event) else list.add(event)
        return edit.copy(events = list)
    }

    /** Soft-delete originals, hard-remove added events. */
    fun deleteEvent(edit: DayEdit, id: String): DayEdit {
        val target = edit.events.find { it.id == id } ?: return edit
        return if (target.origIndex == null) {
            edit.copy(events = edit.events.filterNot { it.id == id })
        } else {
            updateEvent(edit, target.copy(deleted = true))
        }
    }

    fun restoreEvent(edit: DayEdit, id: String): DayEdit {
        val target = edit.events.find { it.id == id } ?: return edit
        return updateEvent(edit, target.copy(deleted = false))
    }

    /** Move a visible event up or down among visible events. */
    fun move(edit: DayEdit, id: String, up: Boolean): DayEdit {
        val list = edit.events.toMutableList()
        val from = list.indexOfFirst { it.id == id }
        if (from < 0) return edit
        var to = from + if (up) -1 else 1
        // Skip over soft-deleted rows so movement matches what the user sees.
        while (to in list.indices && list[to].deleted) to += if (up) -1 else 1
        if (to !in list.indices) return edit
        val item = list.removeAt(from)
        list.add(to, item)
        return edit.copy(events = list)
    }

    /**
     * Move an event to another day. Returns the updated (source, target)
     * pair. The event lands at the end of the target day as an added event.
     */
    fun moveToDay(
        source: DayEdit,
        target: DayEdit,
        id: String,
        newId: String
    ): Pair<DayEdit, DayEdit> {
        val moving = source.events.find { it.id == id && !it.deleted }
            ?: return source to target
        val newSource = deleteEvent(source, id)
        val newTarget = addEvent(target, moving.copy(id = newId, origIndex = null, deleted = false))
        return newSource to newTarget
    }

    fun encode(edit: DayEdit): String = json.encodeToString(edit)

    fun decode(raw: String?): DayEdit? = try {
        if (raw.isNullOrBlank()) null else json.decodeFromString<DayEdit>(raw)
    } catch (_: Exception) {
        null
    }
}
