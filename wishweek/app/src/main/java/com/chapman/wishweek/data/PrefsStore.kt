package com.chapman.wishweek.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore

val Context.dataStore by preferencesDataStore(name = "wishweek_prefs")

/**
 * All persisted state: checklist checks, placeholder overrides, kid mode, and
 * parent-entered medical notes. Everything stays on this device.
 */
object PrefsStore {

    fun checklistKey(listId: String) = stringSetPreferencesKey("chk_$listId")
    fun checklistDateKey(listId: String) = stringPreferencesKey("chkdate_$listId")
    fun overrideKey(token: String) = stringPreferencesKey("ph_$token")
    val KID_MODE = booleanPreferencesKey("kid_mode")
    fun medicalKey(person: String, field: String) =
        stringPreferencesKey("med_${person.lowercase()}_$field")

    fun overridesFrom(prefs: Preferences, tokenNames: Collection<String>): Map<String, String> {
        val out = mutableMapOf<String, String>()
        for (name in tokenNames) {
            val v = prefs[overrideKey(name)]
            if (!v.isNullOrBlank()) out[name] = v
        }
        return out
    }

    fun checkedItems(prefs: Preferences, list: Checklist, today: String): Set<Int> =
        ChecklistLogic.effectiveChecked(
            stored = ChecklistLogic.decode(prefs[checklistKey(list.id)]),
            resetDaily = list.resetDaily,
            storedDate = prefs[checklistDateKey(list.id)],
            today = today
        )

    suspend fun toggleItem(context: Context, list: Checklist, index: Int, today: String) {
        context.dataStore.edit { prefs ->
            val current = ChecklistLogic.effectiveChecked(
                stored = ChecklistLogic.decode(prefs[checklistKey(list.id)]),
                resetDaily = list.resetDaily,
                storedDate = prefs[checklistDateKey(list.id)],
                today = today
            )
            prefs[checklistKey(list.id)] = ChecklistLogic.encode(ChecklistLogic.toggle(current, index))
            prefs[checklistDateKey(list.id)] = today
        }
    }

    suspend fun resetList(context: Context, list: Checklist, today: String) {
        context.dataStore.edit { prefs ->
            prefs[checklistKey(list.id)] = emptySet()
            prefs[checklistDateKey(list.id)] = today
        }
    }

    suspend fun setOverride(context: Context, token: String, value: String) {
        context.dataStore.edit { prefs ->
            if (value.isBlank()) prefs.remove(overrideKey(token))
            else prefs[overrideKey(token)] = value.trim()
        }
    }

    suspend fun setKidMode(context: Context, enabled: Boolean) {
        context.dataStore.edit { prefs -> prefs[KID_MODE] = enabled }
    }

    suspend fun setMedical(context: Context, person: String, field: String, value: String) {
        context.dataStore.edit { prefs -> prefs[medicalKey(person, field)] = value }
    }

    // Budget tracker
    val PURCHASES = stringPreferencesKey("budget_purchases")

    /** Per-kid starting-amount override, editable in-app on top of the token. */
    fun budgetStartKey(kid: String) = stringPreferencesKey("budget_start_${kid.lowercase()}")

    fun budgetStartOverride(prefs: Preferences, kid: String): Int? =
        prefs[budgetStartKey(kid)]?.toIntOrNull()

    suspend fun setBudgetStart(context: Context, kid: String, amount: Int?) {
        context.dataStore.edit { prefs ->
            if (amount == null) prefs.remove(budgetStartKey(kid))
            else prefs[budgetStartKey(kid)] = amount.toString()
        }
    }

    /** Whole medical card override: an edited list of field lines per person. */
    fun medicalCardKey(person: String) = stringPreferencesKey("medcard_${person.lowercase()}")

    fun medicalCardOverride(prefs: Preferences, person: String): List<String>? =
        MedicalFields.decode(prefs[medicalCardKey(person)])

    suspend fun setMedicalCard(context: Context, person: String, fields: List<String>?) {
        context.dataStore.edit { prefs ->
            if (fields == null) prefs.remove(medicalCardKey(person))
            else prefs[medicalCardKey(person)] = MedicalFields.encode(fields)
        }
    }

    fun purchases(prefs: Preferences): List<Purchase> = BudgetLogic.decode(prefs[PURCHASES])

    suspend fun setPurchases(context: Context, purchases: List<Purchase>) {
        context.dataStore.edit { prefs -> prefs[PURCHASES] = BudgetLogic.encode(purchases) }
    }

    // Reminders: per-reminder enabled flag and time override (HH:mm)
    fun reminderEnabledKey(id: String) = booleanPreferencesKey("rem_on_$id")
    fun reminderTimeKey(id: String) = stringPreferencesKey("rem_time_$id")

    fun reminderEnabled(prefs: Preferences, def: ReminderDef): Boolean =
        prefs[reminderEnabledKey(def.id)] ?: def.enabledDefault

    fun reminderTime(prefs: Preferences, def: ReminderDef): String =
        prefs[reminderTimeKey(def.id)] ?: def.time

    suspend fun setReminderEnabled(context: Context, id: String, enabled: Boolean) {
        context.dataStore.edit { prefs -> prefs[reminderEnabledKey(id)] = enabled }
    }

    suspend fun setReminderTime(context: Context, id: String, time: String) {
        context.dataStore.edit { prefs -> prefs[reminderTimeKey(id)] = time }
    }
}
