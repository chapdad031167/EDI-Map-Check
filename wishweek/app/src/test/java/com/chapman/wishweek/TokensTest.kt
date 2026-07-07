package com.chapman.wishweek

import com.chapman.wishweek.data.Segment
import com.chapman.wishweek.data.Tokens
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TokensTest {

    private val placeholders = mapOf<String, String?>(
        "GKTW_FRONT_DESK" to "407-396-1114",
        "FLIGHT_DETAILS" to null,
        "TREX_RESERVATION" to null
    )

    @Test
    fun `filled token substitutes its value`() {
        val out = Tokens.substitute("Call {{GKTW_FRONT_DESK}} now", placeholders)
        assertEquals("Call 407-396-1114 now", out)
    }

    @Test
    fun `unfilled token renders a visible pending marker, never disappears`() {
        val out = Tokens.substitute("Flight: {{FLIGHT_DETAILS}}", placeholders)
        assertEquals("Flight: ${Tokens.pendingLabel("FLIGHT_DETAILS")}", out)
        assertTrue(out.contains("FLIGHT_DETAILS"))
    }

    @Test
    fun `override wins over a null json value`() {
        val overrides = mapOf("FLIGHT_DETAILS" to "SWA 1234, 9:05am CMH to MCO")
        val out = Tokens.substitute("Flight: {{FLIGHT_DETAILS}}", placeholders, overrides)
        assertEquals("Flight: SWA 1234, 9:05am CMH to MCO", out)
    }

    @Test
    fun `override wins over a filled json value`() {
        val overrides = mapOf("GKTW_FRONT_DESK" to "407-000-0000")
        assertEquals(
            "407-000-0000",
            Tokens.resolve("GKTW_FRONT_DESK", placeholders, overrides)
        )
    }

    @Test
    fun `blank override falls back to json value`() {
        val overrides = mapOf("GKTW_FRONT_DESK" to "   ")
        assertEquals(
            "407-396-1114",
            Tokens.resolve("GKTW_FRONT_DESK", placeholders, overrides)
        )
    }

    @Test
    fun `unknown token resolves to null and reads as pending`() {
        assertNull(Tokens.resolve("NOT_A_REAL_TOKEN", placeholders))
        assertTrue(Tokens.hasPending("{{NOT_A_REAL_TOKEN}}", placeholders))
    }

    @Test
    fun `string with no tokens passes through untouched`() {
        val raw = "Buttons on, every park, every day."
        assertEquals(raw, Tokens.substitute(raw, placeholders))
        assertFalse(Tokens.hasPending(raw, placeholders))
    }

    @Test
    fun `multiple tokens in one string are each handled`() {
        val out = Tokens.substitute(
            "{{GKTW_FRONT_DESK}} and {{FLIGHT_DETAILS}} and {{TREX_RESERVATION}}",
            placeholders
        )
        assertTrue(out.startsWith("407-396-1114 and "))
        assertTrue(out.contains(Tokens.pendingLabel("FLIGHT_DETAILS")))
        assertTrue(out.contains(Tokens.pendingLabel("TREX_RESERVATION")))
    }

    @Test
    fun `segments keep surrounding text intact`() {
        val segs = Tokens.segments("A {{GKTW_FRONT_DESK}} B", placeholders)
        assertEquals(3, segs.size)
        assertEquals(Segment.Text("A "), segs[0])
        assertEquals(Segment.Token("GKTW_FRONT_DESK", "407-396-1114"), segs[1])
        assertEquals(Segment.Text(" B"), segs[2])
    }
}
