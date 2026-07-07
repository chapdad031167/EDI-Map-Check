package com.chapman.wishweek.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.datastore.preferences.core.Preferences
import com.chapman.wishweek.data.BudgetLogic
import com.chapman.wishweek.data.DayResolver
import com.chapman.wishweek.data.DisplayDay
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripPhase
import com.chapman.wishweek.ui.components.EventRow
import com.chapman.wishweek.ui.components.PlanBSection
import com.chapman.wishweek.ui.components.TokenText
import com.chapman.wishweek.ui.theme.WishGreen
import com.chapman.wishweek.ui.theme.parkGradient
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun TodayScreen(
    content: TripContent,
    overrides: Map<String, String>,
    displayDays: List<DisplayDay>,
    today: LocalDate,
    evening: Boolean,
    prefs: Preferences,
    onOpenBudget: () -> Unit,
    onOpenJournal: () -> Unit,
    onOpenScrapbook: () -> Unit,
    onOpenEvent: (date: String, eventId: String) -> Unit
) {
    val phase = DayResolver.resolve(today, content)
    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        when (phase) {
            is TripPhase.BeforeTrip -> {
                countdownItems(content, displayDays, phase.daysUntil, onOpenEvent)
                item { BudgetCard(content, overrides, prefs, onOpenBudget) }
            }
            is TripPhase.DuringTrip -> {
                val day = displayDays[phase.dayIndex]
                dayPlanItems(
                    day = day,
                    dayNumber = phase.dayNumber,
                    content = content,
                    overrides = overrides,
                    onOpenEvent = onOpenEvent
                )
                item { BudgetCard(content, overrides, prefs, onOpenBudget) }
                if (evening) {
                    item { TuckInCard(content, today, onOpenJournal) }
                }
            }
            is TripPhase.AfterTrip -> {
                afterTripItems(content)
                item { ScrapbookCard(onOpenScrapbook) }
                item { BudgetCard(content, overrides, prefs, onOpenBudget) }
            }
        }
    }
}

@Composable
private fun BudgetCard(
    content: TripContent,
    overrides: Map<String, String>,
    prefs: Preferences,
    onOpen: () -> Unit
) {
    if (content.budget.envelopes.isEmpty()) return
    val purchases = PrefsStore.purchases(prefs)
    val parts = content.budget.envelopes.map { env ->
        val start = BudgetLogic.effectiveStart(
            Tokens.resolve(env.startAmountToken, content.placeholders, overrides),
            PrefsStore.budgetStartOverride(prefs, env.kid)
        )
        if (start == null) "${env.kid}: 🔶"
        else "${env.kid}: $" + BudgetLogic.remaining(start, purchases, env.kid) + " left"
    }
    val anyPending = parts.any { it.contains("🔶") }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClickLabel = "Open souvenir money") { onOpen() },
        colors = if (anyPending) CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
        else CardDefaults.cardColors()
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = "Souvenir money", style = MaterialTheme.typography.titleSmall)
                Text(
                    text = parts.joinToString("  •  "),
                    style = MaterialTheme.typography.titleMedium,
                    color = if (anyPending) MaterialTheme.colorScheme.onSurface else WishGreen
                )
            }
            Text(text = "💰", fontSize = 30.sp)
        }
    }
}

@Composable
private fun TuckInCard(
    content: TripContent,
    today: LocalDate,
    onOpen: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClickLabel = "Open tuck-in journal") { onOpen() },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = "Tonight's tuck-in", style = MaterialTheme.typography.titleSmall)
                Text(
                    text = "\"${promptFor(content, today.toString())}\"",
                    style = MaterialTheme.typography.titleMedium
                )
            }
            Text(text = "📖", fontSize = 30.sp)
        }
    }
}

@Composable
private fun ScrapbookCard(onOpen: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClickLabel = "Open scrapbook") { onOpen() },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = "The scrapbook is ready", style = MaterialTheme.typography.titleMedium)
                Text(
                    text = "Every page of the week, plus PDF export.",
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            Text(text = "⭐", fontSize = 30.sp)
        }
    }
}

private fun LazyListScope.countdownItems(
    content: TripContent,
    displayDays: List<DisplayDay>,
    daysUntil: Long,
    onOpenEvent: (String, String) -> Unit
) {
    val start = DayResolver.parse(content.meta.tripStart)
    val pretty = start.format(DateTimeFormatter.ofPattern("EEEE, MMMM d"))
    item {
        Card {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(parkGradient("Village"))
                    .padding(28.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(text = "🦖", fontSize = 72.sp)
                Text(
                    text = "$daysUntil",
                    style = MaterialTheme.typography.displayLarge,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    text = if (daysUntil == 1L) "day until Wish Week!" else "days until Wish Week!",
                    style = MaterialTheme.typography.headlineSmall,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "The adventure starts $pretty",
                    style = MaterialTheme.typography.bodyLarge,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
    val firstDay = displayDays.firstOrNull() ?: return
    val firstEvent = firstDay.events.firstOrNull()
    item {
        Text(
            text = "First up when we get there:",
            style = MaterialTheme.typography.titleMedium
        )
    }
    item {
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClickLabel = "Open day one in the itinerary") {
                    firstEvent?.let { onOpenEvent(firstDay.date, it.id) }
                }
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Day 1: ${firstDay.title} ${firstDay.emoji}",
                    style = MaterialTheme.typography.titleLarge
                )
                if (firstDay.park.isNotBlank()) {
                    Text(
                        text = firstDay.park,
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                firstEvent?.let { fe ->
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "▶ ${fe.event.title}",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
            }
        }
    }
}

private fun LazyListScope.dayPlanItems(
    day: DisplayDay,
    dayNumber: Int,
    content: TripContent,
    overrides: Map<String, String>,
    onOpenEvent: (String, String) -> Unit
) {
    item {
        Card {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(parkGradient(day.park))
                    .padding(22.dp)
            ) {
                Text(text = day.emoji, fontSize = 64.sp)
                Text(
                    text = "Day $dayNumber: ${day.title}",
                    style = MaterialTheme.typography.displaySmall
                )
                if (day.park.isNotBlank()) {
                    Text(
                        text = "Today's park: ${day.park}",
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }
        }
    }
    items(day.events, key = { it.id }) { de ->
        EventRow(
            event = de.event,
            family = content.family,
            placeholders = content.placeholders,
            overrides = overrides,
            modified = de.modified || de.added,
            onClick = { onOpenEvent(day.date, de.id) }
        )
    }
    day.planB?.let { planB ->
        item {
            PlanBSection(
                planB = planB,
                placeholders = content.placeholders,
                overrides = overrides
            )
        }
    }
}

private fun LazyListScope.afterTripItems(content: TripContent) {
    item {
        Card {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(parkGradient("Village"))
                    .padding(28.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(text = "⭐", fontSize = 72.sp)
                Text(
                    text = "Wish granted.",
                    style = MaterialTheme.typography.headlineMedium,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(8.dp))
                TokenText(
                    raw = "Ashton's star is in the Castle of Miracles ceiling forever.",
                    placeholders = content.placeholders,
                    overrides = emptyMap(),
                    style = MaterialTheme.typography.bodyLarge
                )
            }
        }
    }
}
