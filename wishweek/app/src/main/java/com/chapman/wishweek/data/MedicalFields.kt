package com.chapman.wishweek.data

import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/** Persisted encoding for edited medical card field lines. */
object MedicalFields {
    private val json = Json { ignoreUnknownKeys = true }

    fun encode(fields: List<String>): String = json.encodeToString(fields)

    fun decode(raw: String?): List<String>? = try {
        if (raw.isNullOrBlank()) null else json.decodeFromString<List<String>>(raw)
    } catch (_: Exception) {
        null
    }
}
