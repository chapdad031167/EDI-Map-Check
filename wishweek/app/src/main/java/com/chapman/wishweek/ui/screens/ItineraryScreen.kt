package com.chapman.wishweek.ui.screens

import androidx.compose.animation.animateContentSize
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.chapman.wishweek.data.DayResolver
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripDay
import com.chapman.wishweek.ui.components.EventRow
import com.chapman.wishweek.ui.components.PlanBSection
import java.time.format.DateTimeFormatter

@Composable
fun ItineraryScreen(
    content: TripContent,
    overrides: Map<String, String>
) {
    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        itemsIndexed(content.days) { index, day ->
            ItineraryDayCard(
                day = day,
                dayNumber = index + 1,
                content = content,
                overrides = overrides
            )
        }
    }
}

@Composable
private fun ItineraryDayCard(
    day: TripDay,
    dayNumber: Int,
    content: TripContent,
    overrides: Map<String, String>
) {
    var expanded by rememberSaveable(day.date) { mutableStateOf(false) }
    val pretty = DayResolver.parse(day.date).format(DateTimeFormatter.ofPattern("EEE, MMM d"))
    Card(modifier = Modifier.animateContentSize()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(16.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "Day $dayNumber ${day.emoji}  $pretty",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Text(text = day.title, style = MaterialTheme.typography.titleMedium)
                    if (day.park.isNotBlank()) {
                        Text(
                            text = day.park,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                Icon(
                    imageVector = if (expanded) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
                    contentDescription = if (expanded) "Collapse" else "Expand"
                )
            }
            if (expanded) {
                Spacer(modifier = Modifier.height(10.dp))
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    day.events.forEach { event ->
                        EventRow(
                            event = event,
                            family = content.family,
                            placeholders = content.placeholders,
                            overrides = overrides
                        )
                    }
                    day.planB?.let { planB ->
                        PlanBSection(
                            planB = planB,
                            placeholders = content.placeholders,
                            overrides = overrides
                        )
                    }
                }
            }
        }
    }
}
