package com.chapman.wishweek

import com.chapman.wishweek.data.BudgetLogic
import com.chapman.wishweek.data.Purchase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BudgetLogicTest {

    @Test
    fun `start amount parses plain and decorated values`() {
        assertEquals(500, BudgetLogic.parseStartAmount("500"))
        assertEquals(500, BudgetLogic.parseStartAmount("$500"))
        assertEquals(500, BudgetLogic.parseStartAmount("500 per kid"))
    }

    @Test
    fun `start amount is null when unfilled or junk`() {
        assertNull(BudgetLogic.parseStartAmount(null))
        assertNull(BudgetLogic.parseStartAmount(""))
        assertNull(BudgetLogic.parseStartAmount("   "))
        assertNull(BudgetLogic.parseStartAmount("soon"))
    }

    @Test
    fun `remaining subtracts only that kid's purchases`() {
        var list = emptyList<Purchase>()
        list = BudgetLogic.add(list, "Ashton", 40, "Build-A-Dino", 1)
        list = BudgetLogic.add(list, "Aedan", 25, "pirate hat", 2)
        list = BudgetLogic.add(list, "Ashton", 10, "", 3)
        assertEquals(450, BudgetLogic.remaining(500, list, "Ashton"))
        assertEquals(475, BudgetLogic.remaining(500, list, "Aedan"))
    }

    @Test
    fun `add rejects zero and negative amounts`() {
        val list = BudgetLogic.add(emptyList(), "Ashton", 0, "", 1)
        assertTrue(list.isEmpty())
        assertTrue(BudgetLogic.add(emptyList(), "Ashton", -5, "", 1).isEmpty())
    }

    @Test
    fun `undo removes only the most recent entry`() {
        var list = emptyList<Purchase>()
        list = BudgetLogic.add(list, "Ashton", 40, "dino", 1)
        list = BudgetLogic.add(list, "Aedan", 25, "hat", 2)
        list = BudgetLogic.undoLast(list)
        assertEquals(1, list.size)
        assertEquals("Ashton", list[0].kid)
        assertEquals(500 - 40, BudgetLogic.remaining(500, list, "Ashton"))
        assertEquals(500, BudgetLogic.remaining(500, list, "Aedan"))
    }

    @Test
    fun `undo on empty list is a no-op`() {
        assertTrue(BudgetLogic.undoLast(emptyList()).isEmpty())
    }

    @Test
    fun `purchases round trip through the persisted encoding`() {
        val list = listOf(
            Purchase("Ashton", 40, "Build-A-Dino", 100),
            Purchase("Aedan", 12, "", 200)
        )
        assertEquals(list, BudgetLogic.decode(BudgetLogic.encode(list)))
    }

    @Test
    fun `decode tolerates junk and null`() {
        assertTrue(BudgetLogic.decode(null).isEmpty())
        assertTrue(BudgetLogic.decode("not json").isEmpty())
    }
}
