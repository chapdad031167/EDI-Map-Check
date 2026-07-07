package com.chapman.wishweek.ui.screens

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
import androidx.datastore.preferences.core.Preferences
import com.chapman.wishweek.data.BudgetLogic
import com.chapman.wishweek.data.DayResolver
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripDay
import com.chapman.wishweek.data.TripPhase
import com.chapman.wishweek.ui.components.EventRow
import com.chapman.wishweek.ui.components.PlanBSection
import com.chapman.wishweek.ui.components.TokenText
import com.chapman.wishweek.ui.theme.WishAmberContainer
import com.chapman.wishweek.ui.theme.WishGreen
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun TodayScreen(
    content: TripContent,
    overrides: Map<String, String>,
    today: LocalDate,
    evening: Boolean,
    prefs: Preferences,
    onOpenBudget: () -> Unit,
    onOpenJournal: () -> Unit,
    onOpenScrapbook: () -> Unit
) {
    val phase = DayResolver.resolve(today, content)
    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        when (phase) {
            is TripPhase.BeforeTrip -> {
                countdownItems(content, phase.daysUntil)
                item { BudgetCard(content, overrides, prefs, onOpenBudget) }
            }
            is TripPhase.DuringTrip -> {
                dayPlanItems(
                    day = content.days[phase.dayIndex],
                    dayNumber = phase.dayNumber,
                    content = content,
                    overrides = overrides
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
        val start = BudgetLogic.parseStartAmount(
            Tokens.resolve(env.startAmountToken, content.placeholders, overrides)
        )
        if (start == null) "${env.kid}: 🔶"
        else "${env.kid}: $" + BudgetLogic.remaining(start, purchases, env.kid) + " left"
    }
    val anyPending = parts.any { it.contains("🔶") }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onOpen() },
        colors = if (anyPending) CardDefaults.cardColors(containerColor = WishAmberContainer)
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
            Text(text = "💰", style = MaterialTheme.typography.headlineSmall)
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
            .clickable { onOpen() },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
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
            Text(text = "📖", style = MaterialTheme.typography.headlineSmall)
        }
    }
}

@Composable
private fun ScrapbookCard(onOpen: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onOpen() },
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
            Text(text = "⭐", style = MaterialTheme.typography.headlineSmall)
        }
    }
}

private fun LazyListScope.countdownItems(content: TripContent, daysUntil: Long) {
    val start = DayResolver.parse(content.meta.tripStart)
    val pretty = start.format(DateTimeFormatter.ofPattern("EEEE, MMMM d"))
    item {
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(text = "🦖", style = MaterialTheme.typography.headlineLarge)
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "$daysUntil days until Wish Week!",
                    style = MaterialTheme.typography.headlineMedium,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "The adventure starts $pretty",
                    style = MaterialTheme.typography.bodyLarge,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
    item {
        Text(
            text = "First up when we get there:",
            style = MaterialTheme.typography.titleMedium
        )
    }
    content.days.firstOrNull()?.let { first ->
        item { DayHeaderCard(first) }
    }
}

@Composable
private fun DayHeaderCard(day: TripDay) {
    Card {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Day 1: ${day.title} ${day.emoji}",
                style = MaterialTheme.typography.titleLarge
            )
            if (day.park.isNotBlank()) {
                Text(
                    text = day.park,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

private fun LazyListScope.dayPlanItems(
    day: TripDay,
    dayNumber: Int,
    content: TripContent,
    overrides: Map<String, String>
) {
    item {
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp)
            ) {
                Text(
                    text = "Day $dayNumber: ${day.title} ${day.emoji}",
                    style = MaterialTheme.typography.headlineSmall
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
    items(day.events) { event ->
        EventRow(
            event = event,
            family = content.family,
            placeholders = content.placeholders,
            overrides = overrides
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
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(text = "⭐", style = MaterialTheme.typography.headlineLarge)
                Spacer(modifier = Modifier.height(12.dp))
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
