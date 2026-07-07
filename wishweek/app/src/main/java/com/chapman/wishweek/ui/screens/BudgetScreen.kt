package com.chapman.wishweek.ui.screens

import androidx.compose.animation.core.animateIntAsState
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.datastore.preferences.core.Preferences
import com.chapman.wishweek.data.BudgetLogic
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.ui.components.prettyTokenName
import com.chapman.wishweek.ui.theme.WishAmberContainer
import com.chapman.wishweek.ui.theme.WishGreen
import kotlinx.coroutines.launch

@Composable
fun BudgetScreen(
    content: TripContent,
    overrides: Map<String, String>,
    prefs: Preferences
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val purchases = PrefsStore.purchases(prefs)

    // In-app edited amounts win over the SOUVENIR_BUDGET token; editing a
    // start amount recomputes remaining and never touches the purchase list.
    val startAmounts = content.budget.envelopes.associate { env ->
        env.kid to BudgetLogic.effectiveStart(
            Tokens.resolve(env.startAmountToken, content.placeholders, overrides),
            PrefsStore.budgetStartOverride(prefs, env.kid)
        )
    }
    val trackerReady = startAmounts.values.all { it != null }

    var pickedKid by rememberSaveable { mutableStateOf("") }
    var amountText by rememberSaveable { mutableStateOf("") }
    var note by rememberSaveable { mutableStateOf("") }
    var editingStartFor by rememberSaveable { mutableStateOf<String?>(null) }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        if (!trackerReady) {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = WishAmberContainer)) {
                    Text(
                        text = "🔶 ${prettyTokenName("SOUVENIR_BUDGET")} is still pending. Fill it in from Settings and the tracker unlocks.",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(16.dp)
                    )
                }
            }
        }
        if (content.budget.showOverallTotal && trackerReady) {
            item {
                val starts = startAmounts.mapValues { it.value ?: 0 }
                val overall by animateIntAsState(
                    targetValue = BudgetLogic.overallRemaining(starts, purchases),
                    label = "overallRemaining"
                )
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(text = "Overall remaining", style = MaterialTheme.typography.titleSmall)
                        Text(
                            text = "$$overall",
                            style = MaterialTheme.typography.displaySmall,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Text(
                            text = content.budget.fundingSource,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                content.budget.envelopes.forEach { env ->
                    val start = startAmounts[env.kid]
                    Card(modifier = Modifier.weight(1f)) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(14.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(text = env.kid, style = MaterialTheme.typography.titleMedium)
                            if (start == null) {
                                Text(
                                    text = "🔶",
                                    style = MaterialTheme.typography.headlineMedium
                                )
                            } else {
                                val remaining by animateIntAsState(
                                    targetValue = BudgetLogic.remaining(start, purchases, env.kid),
                                    label = "remaining_${env.kid}"
                                )
                                Text(
                                    text = "$$remaining",
                                    style = MaterialTheme.typography.headlineMedium,
                                    color = WishGreen
                                )
                            }
                            Text(
                                text = if (start == null) "pending" else "of $$start left",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            if (content.budget.amountsEditableInApp) {
                                TextButton(onClick = { editingStartFor = env.kid }) {
                                    Text("Edit amount")
                                }
                            }
                        }
                    }
                }
            }
        }
        if (content.budget.preApproved.isNotEmpty()) {
            item {
                Column {
                    content.budget.preApproved.forEach {
                        Text(
                            text = "✅ Pre-approved: $it",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
        if (trackerReady) {
            item {
                Card {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        Text(text = "Add a purchase", style = MaterialTheme.typography.titleMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            content.budget.envelopes.forEach { env ->
                                val selected = pickedKid == env.kid
                                Button(
                                    onClick = { pickedKid = env.kid },
                                    modifier = Modifier
                                        .weight(1f)
                                        .height(60.dp),
                                    colors = if (selected) ButtonDefaults.buttonColors()
                                    else ButtonDefaults.buttonColors(
                                        containerColor = MaterialTheme.colorScheme.surfaceVariant,
                                        contentColor = MaterialTheme.colorScheme.onSurface
                                    )
                                ) {
                                    Text(env.kid, fontSize = 20.sp)
                                }
                            }
                        }
                        Text(
                            text = if (amountText.isBlank()) "$0" else "$$amountText",
                            style = MaterialTheme.typography.headlineLarge,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth()
                        )
                        Numpad(
                            onDigit = { d ->
                                if (amountText.length < 4) {
                                    val next = (amountText + d).trimStart('0')
                                    amountText = next
                                }
                            },
                            onBackspace = { amountText = amountText.dropLast(1) },
                            onClear = { amountText = "" }
                        )
                        OutlinedTextField(
                            value = note,
                            onValueChange = { note = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            placeholder = { Text("Note, like Build-A-Dino (optional)") }
                        )
                        Button(
                            onClick = {
                                val amount = amountText.toIntOrNull() ?: 0
                                val kid = pickedKid
                                if (amount > 0 && kid.isNotBlank()) {
                                    scope.launch {
                                        PrefsStore.setPurchases(
                                            context,
                                            BudgetLogic.add(
                                                purchases, kid, amount, note,
                                                System.currentTimeMillis()
                                            )
                                        )
                                    }
                                    amountText = ""
                                    note = ""
                                }
                            },
                            enabled = pickedKid.isNotBlank() && (amountText.toIntOrNull() ?: 0) > 0,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(60.dp)
                        ) {
                            Text("Save purchase", fontSize = 20.sp)
                        }
                    }
                }
            }
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Purchases",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f)
                    )
                    if (purchases.isNotEmpty()) {
                        TextButton(onClick = {
                            scope.launch {
                                PrefsStore.setPurchases(context, BudgetLogic.undoLast(purchases))
                            }
                        }) {
                            Text("Undo last")
                        }
                    }
                }
            }
            if (purchases.isEmpty()) {
                item {
                    Text(
                        text = "Nothing yet. The envelopes are full.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            items(purchases.reversed(), key = { it.at }) { p ->
                Card {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "${p.kid}${if (p.note.isNotBlank()) ": ${p.note}" else ""}",
                                style = MaterialTheme.typography.bodyLarge
                            )
                        }
                        Text(
                            text = "-$${p.amount}",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.error
                        )
                    }
                }
            }
        }
    }

    editingStartFor?.let { kid ->
        StartAmountDialog(
            kid = kid,
            current = startAmounts[kid],
            onDismiss = { editingStartFor = null },
            onSave = { amount ->
                editingStartFor = null
                scope.launch { PrefsStore.setBudgetStart(context, kid, amount) }
            }
        )
    }
}

@Composable
private fun StartAmountDialog(
    kid: String,
    current: Int?,
    onDismiss: () -> Unit,
    onSave: (Int?) -> Unit
) {
    var text by rememberSaveable(kid) { mutableStateOf(current?.toString() ?: "") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("$kid's starting amount") },
        text = {
            Column {
                OutlinedTextField(
                    value = text,
                    onValueChange = { new -> text = new.filter { it.isDigit() }.take(5) },
                    label = { Text("Whole dollars") },
                    singleLine = true
                )
                Text(
                    text = "Purchases already logged are kept; the remaining balance just recomputes.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onSave(text.toIntOrNull()) },
                enabled = text.toIntOrNull() != null
            ) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
private fun Numpad(
    onDigit: (Char) -> Unit,
    onBackspace: () -> Unit,
    onClear: () -> Unit
) {
    val rows = listOf("123", "456", "789")
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        rows.forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { d ->
                    NumKey(text = d.toString(), modifier = Modifier.weight(1f)) { onDigit(d) }
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumKey(text = "C", modifier = Modifier.weight(1f), onClick = onClear)
            NumKey(text = "0", modifier = Modifier.weight(1f)) { onDigit('0') }
            NumKey(text = "⌫", modifier = Modifier.weight(1f), onClick = onBackspace)
        }
    }
}

@Composable
private fun NumKey(text: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.height(64.dp)
    ) {
        Text(text = text, fontSize = 26.sp)
    }
}
