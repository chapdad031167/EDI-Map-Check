package com.chapman.wishweek.ui.screens

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.datastore.preferences.core.Preferences
import com.chapman.wishweek.data.Checklist
import com.chapman.wishweek.data.PrefsStore
import kotlinx.coroutines.launch

/** A checkbox that gives a satisfying bounce when ticked. */
@Composable
private fun BouncyCheckbox(checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    val scale = remember { Animatable(1f) }
    var previous by remember { mutableStateOf(checked) }
    LaunchedEffect(checked) {
        if (checked && !previous) {
            scale.snapTo(1f)
            scale.animateTo(1.35f, tween(durationMillis = 90))
            scale.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy))
        }
        previous = checked
    }
    Checkbox(
        checked = checked,
        onCheckedChange = onCheckedChange,
        modifier = Modifier.scale(scale.value)
    )
}

@Composable
fun ChecklistsScreen(
    checklists: List<Checklist>,
    prefs: Preferences,
    today: String
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        items(checklists) { list ->
            val checked = PrefsStore.checkedItems(prefs, list, today)
            Card {
                Column(modifier = Modifier.padding(vertical = 10.dp, horizontal = 14.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(text = list.name, style = MaterialTheme.typography.titleMedium)
                            val progress = "${checked.size} of ${list.items.size} done" +
                                if (list.resetDaily) " (resets each morning)" else ""
                            Text(
                                text = progress,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        TextButton(onClick = {
                            scope.launch { PrefsStore.resetList(context, list, today) }
                        }) {
                            Text("Reset")
                        }
                    }
                    list.items.forEachIndexed { index, item ->
                        val isChecked = index in checked
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    scope.launch {
                                        PrefsStore.toggleItem(context, list, index, today)
                                    }
                                }
                                .padding(vertical = 2.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            BouncyCheckbox(
                                checked = isChecked,
                                onCheckedChange = {
                                    scope.launch {
                                        PrefsStore.toggleItem(context, list, index, today)
                                    }
                                }
                            )
                            Spacer(modifier = Modifier.padding(start = 2.dp))
                            Text(
                                text = item,
                                style = MaterialTheme.typography.bodyLarge,
                                textDecoration = if (isChecked) TextDecoration.LineThrough else null,
                                color = if (isChecked) MaterialTheme.colorScheme.onSurfaceVariant
                                else MaterialTheme.colorScheme.onSurface
                            )
                        }
                    }
                }
            }
        }
    }
}
