package com.chapman.wishweek.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.journal.JournalDb
import com.chapman.wishweek.journal.PdfExporter
import com.chapman.wishweek.journal.Photos
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun ScrapbookScreen(content: TripContent) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val dao = remember { JournalDb.get(context).dao() }
    val entries by dao.allEntries().collectAsState(initial = emptyList())
    var exportResult by remember { mutableStateOf<String?>(null) }

    val byDate = entries.filter { it.text.isNotBlank() || it.photoPath != null }
        .groupBy { it.date }
        .toSortedMap()

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Column {
                Text(
                    text = "Ashton's Wish Week",
                    style = MaterialTheme.typography.headlineSmall
                )
                Text(
                    text = "The scrapbook. One page per day, written by all of us.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        item {
            Button(
                onClick = {
                    scope.launch {
                        val result = withContext(Dispatchers.IO) {
                            PdfExporter.export(context, content, entries)
                        }
                        exportResult = result?.let { "Saved to $it" }
                            ?: "Nothing to export yet. Write a line first."
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp),
                enabled = byDate.isNotEmpty()
            ) {
                Text("Export scrapbook PDF")
            }
        }
        exportResult?.let { msg ->
            item {
                Text(text = msg, style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (byDate.isEmpty()) {
            item {
                Text(
                    text = "No pages yet. Entries show up here as the week fills in.",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        items(byDate.keys.toList()) { date ->
            val dayIndex = content.days.indexOfFirst { it.date == date }
            val day = content.days.getOrNull(dayIndex)
            Card {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = if (day != null) "Day ${dayIndex + 1}: ${day.title} ${day.emoji}" else date,
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = "\"${promptFor(content, date)}\"",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                    byDate[date].orEmpty().sortedBy { it.person }.forEach { entry ->
                        if (entry.text.isNotBlank()) {
                            Text(
                                text = "${entry.person}: \"${entry.text}\"",
                                style = MaterialTheme.typography.bodyLarge
                            )
                        }
                        entry.photoPath?.let { path ->
                            val bitmap = remember(path) { Photos.decodeScaled(path, 700) }
                            if (bitmap != null) {
                                Image(
                                    bitmap = bitmap.asImageBitmap(),
                                    contentDescription = "${entry.person}'s photo",
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(180.dp),
                                    contentScale = ContentScale.Crop
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
