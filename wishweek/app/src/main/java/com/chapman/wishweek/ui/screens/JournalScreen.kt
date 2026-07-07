package com.chapman.wishweek.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.journal.JournalDb
import com.chapman.wishweek.journal.JournalEntry
import com.chapman.wishweek.journal.Photos
import kotlinx.coroutines.launch
import java.time.LocalDate

fun promptFor(content: TripContent, date: String): String =
    content.journalPrompts[date]
        ?: content.journalPrompts["default"]
        ?: "Best thing today?"

@Composable
fun JournalScreen(
    content: TripContent,
    date: LocalDate,
    onOpenScrapbook: () -> Unit
) {
    val context = LocalContext.current
    val dateKey = date.toString()
    val dao = remember { JournalDb.get(context).dao() }
    val entries by dao.entriesFor(dateKey).collectAsState(initial = emptyList())
    val prompt = promptFor(content, dateKey)

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Column {
                Text(text = "Tonight's tuck-in", style = MaterialTheme.typography.titleLarge)
                Text(
                    text = "\"$prompt\"",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    text = "One line each. Photos optional. Future you says thanks.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        items(content.family, key = { it.name }) { member ->
            PersonEntryCard(
                person = member.name,
                dateKey = dateKey,
                saved = entries.find { it.person == member.name }
            )
        }
        item {
            TextButton(onClick = onOpenScrapbook, modifier = Modifier.fillMaxWidth()) {
                Text("Open the scrapbook")
            }
        }
    }
}

@Composable
private fun PersonEntryCard(
    person: String,
    dateKey: String,
    saved: JournalEntry?
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val dao = remember { JournalDb.get(context).dao() }

    var text by rememberSaveable(dateKey, person) { mutableStateOf("") }
    var seeded by rememberSaveable(dateKey, person) { mutableStateOf(false) }
    LaunchedEffect(saved) {
        if (!seeded && saved != null && text.isBlank()) text = saved.text
        if (saved != null || text.isNotBlank()) seeded = true
    }

    // Bump to force photo reload after a retake overwrites the same file.
    var photoVersion by rememberSaveable(dateKey, person) { mutableStateOf(0) }
    val photoPath = saved?.photoPath

    fun save(newText: String = text, newPhoto: String? = photoPath) {
        scope.launch {
            dao.upsert(JournalEntry(dateKey, person, newText, newPhoto))
        }
    }

    val photoFile = Photos.photoFile(context, dateKey, person)
    val takePhoto = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) {
            photoVersion++
            save(newPhoto = photoFile.absolutePath)
        }
    }
    val pickPhoto = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        if (uri != null && Photos.copyIn(context, uri, photoFile)) {
            photoVersion++
            save(newPhoto = photoFile.absolutePath)
        }
    }

    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(text = person, style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = text,
                onValueChange = { new ->
                    text = new
                    save(newText = new)
                },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("One line is plenty") }
            )
            if (photoPath != null) {
                val bitmap = remember(photoPath, photoVersion) {
                    Photos.decodeScaled(photoPath, 800)
                }
                if (bitmap != null) {
                    Image(
                        bitmap = bitmap.asImageBitmap(),
                        contentDescription = "$person's photo",
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(200.dp),
                        contentScale = ContentScale.Crop
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    runCatching { takePhoto.launch(Photos.uriFor(context, photoFile)) }
                }) {
                    Text("📷 Take photo")
                }
                OutlinedButton(onClick = {
                    pickPhoto.launch(
                        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                    )
                }) {
                    Text("🖼️ Pick photo")
                }
            }
        }
    }
}
