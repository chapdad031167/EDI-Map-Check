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
}
