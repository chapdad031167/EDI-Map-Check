package com.chapman.wishweek

import com.chapman.wishweek.data.ItineraryLogic
import com.chapman.wishweek.data.TripDay
import com.chapman.wishweek.data.TripEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ItineraryLogicTest {

    private val base = TripDay(
        date = "2026-12-02",
        title = "DINO DAY 🦖",
        emoji = "🦖",
        park = "Islands of Adventure",
        events = listOf(
            TripEvent(time = "Morning", title = "Discovery Center", mustDo = true),
            TripEvent(time = "AM", title = "Raptor Encounter", mustDo = true),
            TripEvent(time = "Afternoon", title = "River Adventure", heightMin = 42)
        ),
        planB = "Rain plan"
    )

    private val otherBase = TripDay(
        date = "2026-12-03",
        title = "Village Rest Day",
        emoji = "🍦",
        park = "Give Kids the World Village",
        events = listOf(TripEvent(time = "Morning", title = "Ice cream for breakfast", mustDo = true))
    )

    @Test
    fun `no override renders the base plan untouched`() {
        val d = ItineraryLogic.display(base, null)
        assertEquals(3, d.events.size)
        assertFalse(d.dayModified)
        assertTrue(d.events.none { it.modified || it.added })
        assertEquals("Rain plan", d.planB)
    }

    @Test
    fun `a fresh seed is an identity override`() {
        val seed = ItineraryLogic.seed(base)
        assertTrue(ItineraryLogic.isIdentity(seed, base))
        assertFalse(ItineraryLogic.display(base, seed).dayModified)
    }

    @Test
    fun `editing an event marks it and the day modified`() {
        val seed = ItineraryLogic.seed(base)
        val target = seed.events[1]
        val edited = ItineraryLogic.updateEvent(seed, target.copy(time = "Midday"))
        val d = ItineraryLogic.display(base, edited)
        assertTrue(d.dayModified)
        assertTrue(d.events[1].modified)
        assertFalse(d.events[0].modified)
        assertFalse(ItineraryLogic.isIdentity(edited, base))
    }

    @Test
    fun `adding an event shows it as added`() {
        val seed = ItineraryLogic.seed(base)
        val added = ItineraryLogic.addEvent(
            seed,
            com.chapman.wishweek.data.EditedEvent(id = "add_1", title = "Churro stop"),
            afterId = seed.events[0].id
        )
        val d = ItineraryLogic.display(base, added)
        assertEquals(4, d.events.size)
        assertEquals("Churro stop", d.events[1].event.title)
        assertTrue(d.events[1].added)
        assertTrue(d.dayModified)
    }

    @Test
    fun `deleting an original event is a soft delete and restorable`() {
        val seed = ItineraryLogic.seed(base)
        val id = seed.events[2].id
        val deleted = ItineraryLogic.deleteEvent(seed, id)
        assertEquals(2, ItineraryLogic.display(base, deleted).events.size)
        assertEquals(3, deleted.events.size)
        val restored = ItineraryLogic.restoreEvent(deleted, id)
        assertEquals(3, ItineraryLogic.display(base, restored).events.size)
        assertTrue(ItineraryLogic.isIdentity(restored, base))
    }

    @Test
    fun `deleting an added event removes it outright`() {
        val seed = ItineraryLogic.seed(base)
        val withAdd = ItineraryLogic.addEvent(
            seed, com.chapman.wishweek.data.EditedEvent(id = "add_2", title = "Extra")
        )
        val gone = ItineraryLogic.deleteEvent(withAdd, "add_2")
        assertTrue(ItineraryLogic.isIdentity(gone, base))
    }

    @Test
    fun `reorder marks the day modified and move respects bounds`() {
        val seed = ItineraryLogic.seed(base)
        val moved = ItineraryLogic.move(seed, seed.events[2].id, up = true)
        val d = ItineraryLogic.display(base, moved)
        assertEquals("River Adventure", d.events[1].event.title)
        assertTrue(d.dayModified)
        // Moving the first event up is a no-op.
        assertEquals(moved, ItineraryLogic.move(moved, moved.events[0].id, up = true))
        // Moving back down restores identity.
        val back = ItineraryLogic.move(moved, seed.events[2].id, up = false)
        assertTrue(ItineraryLogic.isIdentity(back, base))
    }

    @Test
    fun `move to another day lands at the end as an added event`() {
        val source = ItineraryLogic.seed(base)
        val target = ItineraryLogic.seed(otherBase)
        val id = source.events[1].id
        val (newSource, newTarget) = ItineraryLogic.moveToDay(source, target, id, "add_moved")
        // Source: soft-deleted original.
        assertEquals(2, ItineraryLogic.display(base, newSource).events.size)
        // Target: appended as added.
        val td = ItineraryLogic.display(otherBase, newTarget)
        assertEquals(2, td.events.size)
        assertEquals("Raptor Encounter", td.events.last().event.title)
        assertTrue(td.events.last().added)
        assertTrue(td.dayModified)
    }

    @Test
    fun `day field edits mark the day modified`() {
        val seed = ItineraryLogic.seed(base).copy(title = "MEGA DINO DAY")
        assertTrue(ItineraryLogic.display(base, seed).dayModified)
        assertFalse(ItineraryLogic.isIdentity(seed, base))
    }

    @Test
    fun `override round trips through the persisted encoding`() {
        val seed = ItineraryLogic.seed(base)
        val edited = ItineraryLogic.updateEvent(seed, seed.events[0].copy(notes = "bring ponchos"))
        val decoded = ItineraryLogic.decode(ItineraryLogic.encode(edited))
        assertEquals(edited, decoded)
    }

    @Test
    fun `decode tolerates junk`() {
        assertNull(ItineraryLogic.decode(null))
        assertNull(ItineraryLogic.decode("not json"))
    }
}
