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
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.ui.components.prettyTokenName
import com.chapman.wishweek.ui.theme.WishAmberContainer
import com.chapman.wishweek.ui.theme.WishRed
import kotlinx.coroutines.launch

private val ASHTON_FIELDS = listOf(
    "history" to "Medical history",
    "meds" to "Current meds",
    "allergies" to "Allergies"
)

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
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text(
                text = "One tap opens the dialer with the number ready.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        items(content.emergency.contacts) { contact ->
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
                Card(colors = CardDefaults.cardColors(containerColor = WishAmberContainer)) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "🔶 ${contact.label}: number pending (${prettyTokenName(contact.phoneToken)}). Fill it in from Settings.",
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }
            }
        }
        items(content.emergency.medicalCards) { card ->
            Card {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Text(
                        text = "${card.person}'s medical card",
                        style = MaterialTheme.typography.titleMedium,
                        color = WishRed
                    )
                    card.fields.forEach { field ->
                        if (!field.contains("parent-entered", ignoreCase = true)) {
                            Text(text = "• $field", style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                    if (card.person.equals("Ashton", ignoreCase = true)) {
                        Text(
                            text = "Parent-entered details (saved on this phone only):",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        ASHTON_FIELDS.forEach { (fieldKey, label) ->
                            MedicalField(person = card.person, fieldKey = fieldKey, label = label, prefs = prefs)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun MedicalField(
    person: String,
    fieldKey: String,
    label: String,
    prefs: Preferences
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val saved = prefs[PrefsStore.medicalKey(person, fieldKey)] ?: ""
    var text by rememberSaveable(fieldKey) { mutableStateOf(saved) }
    // Adopt persisted value once DataStore loads after first composition.
    var seeded by rememberSaveable(fieldKey) { mutableStateOf(false) }
    LaunchedEffect(saved) {
        if (!seeded && saved.isNotBlank() && text.isBlank()) text = saved
        seeded = true
    }
    OutlinedTextField(
        value = text,
        onValueChange = { new ->
            text = new
            scope.launch { PrefsStore.setMedical(context, person, fieldKey, new) }
        },
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label) },
        minLines = 1
    )
}
