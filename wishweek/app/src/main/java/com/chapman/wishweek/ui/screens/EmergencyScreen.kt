package com.chapman.wishweek.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import com.chapman.wishweek.data.MedicalCard
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.ui.components.prettyTokenName
import com.chapman.wishweek.ui.theme.WishRed
import kotlinx.coroutines.launch

@Composable
fun EmergencyScreen(
    content: TripContent,
    overrides: Map<String, String>,
    prefs: Preferences
) {
    val context = LocalContext.current

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Text(
                text = "One tap opens the dialer with the number ready.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        items(content.emergency.contacts, key = { it.phoneToken }) { contact ->
            val number = Tokens.resolve(contact.phoneToken, content.placeholders, overrides)
            if (number != null) {
                Button(
                    onClick = {
                        val tel = number.filter { it.isDigit() || it == '+' }
                        runCatching {
                            context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$tel")))
                        }
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(64.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = WishRed)
                ) {
                    Icon(Icons.Filled.Phone, contentDescription = null)
                    Spacer(modifier = Modifier.padding(start = 10.dp))
                    Text(
                        text = "${contact.label}  •  $number",
                        style = MaterialTheme.typography.labelLarge
                    )
                }
            } else {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)) {
                    Text(
                        text = "🔶 ${contact.label}: number pending (${prettyTokenName(contact.phoneToken)}). Fill it in from Settings.",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp)
                    )
                }
            }
        }
        items(content.emergency.medicalCards, key = { it.person }) { card ->
            MedicalCardView(card = card, prefs = prefs)
        }
    }
}

/**
 * A medical card seeded from the JSON. Every line is parent-editable in-app;
 * edits persist in DataStore as a whole-card override and survive updates.
 */
@Composable
private fun MedicalCardView(card: MedicalCard, prefs: Preferences) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val override = PrefsStore.medicalCardOverride(prefs, card.person)
    // One-time courtesy migration from the v1.x Ashton free-text fields.
    val legacyExtras = if (override == null && card.person.equals("Ashton", ignoreCase = true)) {
        listOf("history" to "History", "meds" to "Current meds", "allergies" to "Allergies")
            .mapNotNull { (key, label) ->
                prefs[PrefsStore.medicalKey(card.person, key)]
                    ?.takeIf { it.isNotBlank() }
                    ?.let { "$label: $it" }
            }
    } else emptyList()
    val effective = override ?: (card.fields + legacyExtras)

    var editing by rememberSaveable(card.person) { mutableStateOf(false) }
    var draft by rememberSaveable(card.person, editing) { mutableStateOf(effective) }

    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "🩺 ${card.person}",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f)
                )
                if (override != null && !editing) {
                    TextButton(onClick = {
                        scope.launch { PrefsStore.setMedicalCard(context, card.person, null) }
                    }) { Text("Reset") }
                }
                if (card.editable) {
                    TextButton(onClick = {
                        if (editing) {
                            val cleaned = draft.map { it.trim() }.filter { it.isNotBlank() }
                            scope.launch { PrefsStore.setMedicalCard(context, card.person, cleaned) }
                        }
                        editing = !editing
                    }) {
                        Text(if (editing) "Save" else "Edit")
                    }
                }
            }
            if (!editing) {
                effective.forEach { field ->
                    Text(text = "• $field", style = MaterialTheme.typography.bodyLarge)
                }
            } else {
                draft.forEachIndexed { index, line ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(
                            value = line,
                            onValueChange = { new ->
                                draft = draft.toMutableList().also { it[index] = new }
                            },
                            modifier = Modifier.weight(1f)
                        )
                        IconButton(onClick = {
                            draft = draft.toMutableList().also { it.removeAt(index) }
                        }) {
                            Icon(Icons.Filled.Clear, contentDescription = "Remove line")
                        }
                    }
                }
                TextButton(onClick = { draft = draft + "" }) {
                    Icon(Icons.Filled.Add, contentDescription = null)
                    Spacer(modifier = Modifier.padding(start = 4.dp))
                    Text("Add a line")
                }
            }
            Text(
                text = "Stays on this phone only.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
