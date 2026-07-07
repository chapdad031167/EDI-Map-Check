package com.chapman.wishweek.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.datastore.preferences.core.Preferences
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.ReminderDef
import com.chapman.wishweek.data.ReminderLogic
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.notify.ReminderScheduler
import com.chapman.wishweek.ui.components.prettyTokenName
import com.chapman.wishweek.ui.theme.WishAmberContainer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Settings: kid mode toggle, reminder controls, and the Fill In The Blanks
 * editor. Every placeholder token is listed with its current value; edits are
 * saved to DataStore as overrides layered on top of the bundled JSON, so no
 * rebuild is ever needed to fill in a blank.
 */
@Composable
fun SettingsScreen(
    content: TripContent,
    overrides: Map<String, String>,
    kidMode: Boolean,
    prefs: Preferences
) {
    val placeholders = content.placeholders
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Card {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(text = "Kid Mode", style = MaterialTheme.typography.titleMedium)
                        Text(
                            text = "Giant buttons, today's adventure, dino facts, and the roar button.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Switch(
                        checked = kidMode,
                        onCheckedChange = { on ->
                            scope.launch { PrefsStore.setKidMode(context, on) }
                        }
                    )
                }
            }
        }
        if (content.reminders.isNotEmpty()) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(text = "Reminders", style = MaterialTheme.typography.titleLarge)
                    Text(
                        text = "Local notifications only, and only between ${content.meta.tripStart} and ${content.meta.tripEnd}. Meal and snack nudges skip Village days.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            items(content.reminders, key = { it.id }) { def ->
                ReminderEditor(def = def, prefs = prefs)
            }
        }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(text = "Fill In The Blanks", style = MaterialTheme.typography.titleLarge)
                Text(
                    text = "Tap any value to update it. Changes save instantly on this phone; the app never needs a rebuild.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        items(placeholders.keys.sorted()) { token ->
            TokenEditor(
                token = token,
                jsonValue = placeholders[token],
                overrideValue = overrides[token]
            )
        }
    }
}

@Composable
private fun ReminderEditor(def: ReminderDef, prefs: Preferences) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val enabled = PrefsStore.reminderEnabled(prefs, def)
    val savedTime = PrefsStore.reminderTime(prefs, def)

    var timeText by rememberSaveable(def.id) { mutableStateOf(savedTime) }
    val timeValid = ReminderLogic.parseTime(timeText) != null

    fun reschedule() {
        scope.launch(Dispatchers.IO) { ReminderScheduler.rescheduleAll(context) }
    }

    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(text = def.label, style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = if (def.type == ReminderLogic.TYPE_PARK_DAYS) "Park days only" else "Every trip day",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Switch(
                    checked = enabled,
                    onCheckedChange = { on ->
                        scope.launch {
                            PrefsStore.setReminderEnabled(context, def.id, on)
                            reschedule()
                        }
                    }
                )
            }
            OutlinedTextField(
                value = timeText,
                onValueChange = { new ->
                    timeText = new
                    if (ReminderLogic.parseTime(new) != null) {
                        scope.launch {
                            PrefsStore.setReminderTime(context, def.id, new.trim())
                            reschedule()
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                isError = !timeValid,
                label = { Text(if (timeValid) "Time (24h HH:mm)" else "Needs HH:mm, like 14:00") }
            )
        }
    }
}

@Composable
private fun TokenEditor(
    token: String,
    jsonValue: String?,
    overrideValue: String?
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val effective = overrideValue ?: jsonValue
    val pending = effective.isNullOrBlank()

    var text by rememberSaveable(token) { mutableStateOf(overrideValue ?: "") }
    var seeded by rememberSaveable(token) { mutableStateOf(false) }
    LaunchedEffect(overrideValue) {
        if (!seeded && !overrideValue.isNullOrBlank() && text.isBlank()) text = overrideValue
        seeded = true
    }

    Card(
        colors = if (pending) CardDefaults.cardColors(containerColor = WishAmberContainer)
        else CardDefaults.cardColors()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Text(
                text = (if (pending) "🔶 " else "✅ ") + prettyTokenName(token),
                style = MaterialTheme.typography.titleSmall
            )
            if (!jsonValue.isNullOrBlank()) {
                Text(
                    text = "From trip file: $jsonValue",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            OutlinedTextField(
                value = text,
                onValueChange = { new ->
                    text = new
                    scope.launch { PrefsStore.setOverride(context, token, new) }
                },
                modifier = Modifier.fillMaxWidth(),
                placeholder = {
                    Text(if (pending) "Still waiting on this one" else "Override the trip file value")
                }
            )
        }
    }
}
