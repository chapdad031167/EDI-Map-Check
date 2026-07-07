package com.chapman.wishweek.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
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
import com.chapman.wishweek.data.DayResolver
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripDay
import com.chapman.wishweek.data.TripPhase
import com.chapman.wishweek.ui.components.EventRow
import com.chapman.wishweek.ui.components.PlanBSection
import com.chapman.wishweek.ui.components.TokenText
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun TodayScreen(
    content: TripContent,
    overrides: Map<String, String>,
    today: LocalDate
) {
    when (val phase = DayResolver.resolve(today, content)) {
        is TripPhase.BeforeTrip -> CountdownView(content, phase.daysUntil)
        is TripPhase.DuringTrip -> DayPlanView(
            day = content.days[phase.dayIndex],
            dayNumber = phase.dayNumber,
            content = content,
            overrides = overrides
        )
        is TripPhase.AfterTrip -> AfterTripView(content)
    }
}

@Composable
private fun CountdownView(content: TripContent, daysUntil: Long) {
    val start = DayResolver.parse(content.meta.tripStart)
    val pretty = start.format(DateTimeFormatter.ofPattern("EEEE, MMMM d"))
    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
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
            item { DayHeaderCard(first, 1) }
        }
    }
}

@Composable
private fun DayHeaderCard(day: TripDay, dayNumber: Int) {
    Card {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Day $dayNumber: ${day.title} ${day.emoji}",
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

@Composable
private fun DayPlanView(
    day: TripDay,
    dayNumber: Int,
    content: TripContent,
    overrides: Map<String, String>
) {
    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
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
}

@Composable
private fun AfterTripView(content: TripContent) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(modifier = Modifier.height(48.dp))
        Text(text = "⭐", style = MaterialTheme.typography.headlineLarge)
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "Wish granted.",
            style = MaterialTheme.typography.headlineMedium,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(8.dp))
        TokenText(
            raw = "Ashton's star is in the Castle of Miracles ceiling forever. Thanks for a magical week, ${content.meta.appName} crew.",
            placeholders = content.placeholders,
            overrides = emptyMap(),
            style = MaterialTheme.typography.bodyLarge
        )
    }
}
