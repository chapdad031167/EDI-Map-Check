package com.chapman.wishweek.data

/**
 * Placeholder token engine. Any content string may embed {{TOKEN}} markers.
 * Values come from the JSON placeholders map, with in-app overrides (saved to
 * DataStore) taking precedence. A token with no usable value anywhere is
 * "pending" and must stay visible in the UI as an amber chip.
 */
sealed class Segment {
    data class Text(val text: String) : Segment()

    /** value == null means the token is unfilled (pending). */
    data class Token(val name: String, val value: String?) : Segment()
}

object Tokens {
    private val PATTERN = Regex("\\{\\{([A-Za-z0-9_]+)\\}\\}")

    /** Override wins if non-blank, else the JSON value if non-blank, else null. */
    fun resolve(
        name: String,
        placeholders: Map<String, String?>,
        overrides: Map<String, String> = emptyMap()
    ): String? {
        val override = overrides[name]
        if (!override.isNullOrBlank()) return override
        val fromJson = placeholders[name]
        if (!fromJson.isNullOrBlank()) return fromJson
        return null
    }

    /** Split a raw string into text and token segments for rendering. */
    fun segments(
        raw: String,
        placeholders: Map<String, String?>,
        overrides: Map<String, String> = emptyMap()
    ): List<Segment> {
        val out = mutableListOf<Segment>()
        var last = 0
        for (match in PATTERN.findAll(raw)) {
            if (match.range.first > last) {
                out.add(Segment.Text(raw.substring(last, match.range.first)))
            }
            val name = match.groupValues[1]
            out.add(Segment.Token(name, resolve(name, placeholders, overrides)))
            last = match.range.last + 1
        }
        if (last < raw.length) out.add(Segment.Text(raw.substring(last)))
        return out
    }

    /**
     * Flat substitution for places that need a plain string. Pending tokens
     * render as a visible marker instead of silently disappearing.
     */
    fun substitute(
        raw: String,
        placeholders: Map<String, String?>,
        overrides: Map<String, String> = emptyMap()
    ): String = segments(raw, placeholders, overrides).joinToString("") { seg ->
        when (seg) {
            is Segment.Text -> seg.text
            is Segment.Token -> seg.value ?: pendingLabel(seg.name)
        }
    }

    fun pendingLabel(name: String): String = "[$name pending]"

    /** True if the string still contains at least one unfilled token. */
    fun hasPending(
        raw: String,
        placeholders: Map<String, String?>,
        overrides: Map<String, String> = emptyMap()
    ): Boolean = segments(raw, placeholders, overrides)
        .any { it is Segment.Token && it.value == null }
}
