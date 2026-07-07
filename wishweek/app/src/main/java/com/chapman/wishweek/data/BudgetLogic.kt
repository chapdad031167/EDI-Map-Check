package com.chapman.wishweek.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * Souvenir envelope math, whole dollars only, Android-free for unit testing.
 * Purchases persist as one JSON string in DataStore.
 */
@Serializable
data class Purchase(
    val kid: String,
    val amount: Int,
    val note: String = "",
    val at: Long = 0
)

object BudgetLogic {

    private val json = Json { ignoreUnknownKeys = true }

    /** "500" or "$500" or "500 per kid" all read as 500. Null if no digits. */
    fun parseStartAmount(tokenValue: String?): Int? {
        if (tokenValue.isNullOrBlank()) return null
        val digits = tokenValue.filter { it.isDigit() }
        return digits.toIntOrNull()
    }

    /** In-app edited amount wins over the token value. */
    fun effectiveStart(tokenValue: String?, editedAmount: Int?): Int? =
        editedAmount ?: parseStartAmount(tokenValue)

    /** Sum of every kid's remaining, for the overall header. */
    fun overallRemaining(starts: Map<String, Int>, purchases: List<Purchase>): Int =
        starts.entries.sumOf { (kid, start) -> remaining(start, purchases, kid) }

    fun spent(purchases: List<Purchase>, kid: String): Int =
        purchases.filter { it.kid == kid }.sumOf { it.amount }

    fun remaining(start: Int, purchases: List<Purchase>, kid: String): Int =
        start - spent(purchases, kid)

    /** Rejects non-positive amounts by returning the list unchanged. */
    fun add(purchases: List<Purchase>, kid: String, amount: Int, note: String, at: Long): List<Purchase> =
        if (amount <= 0) purchases else purchases + Purchase(kid, amount, note.trim(), at)

    /** Undo removes the most recently added entry. */
    fun undoLast(purchases: List<Purchase>): List<Purchase> =
        if (purchases.isEmpty()) purchases else purchases.dropLast(1)

    fun encode(purchases: List<Purchase>): String = json.encodeToString(purchases)

    fun decode(raw: String?): List<Purchase> = try {
        if (raw.isNullOrBlank()) emptyList() else json.decodeFromString(raw)
    } catch (_: Exception) {
        emptyList()
    }
}
