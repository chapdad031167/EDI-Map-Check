package com.chapman.wishweek.ui.screens

import androidx.activity.compose.BackHandler
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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.chapman.wishweek.data.DayEdit
import com.chapman.wishweek.data.DayResolver
import com.chapman.wishweek.data.DisplayDay
import com.chapman.wishweek.data.EditedEvent
import com.chapman.wishweek.data.ItineraryLogic
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripDay
import com.chapman.wishweek.journal.DayOverrideRow
import com.chapman.wishweek.journal.JournalDb
import com.chapman.wishweek.ui.components.EventRow
import com.chapman.wishweek.ui.components.ModifiedDot
import com.chapman.wishweek.ui.components.PlanBSection
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.format.DateTimeFormatter
import java.util.UUID

data class ItineraryFocus(val date: String, val eventId: String)

@Composable
fun ItineraryScreen(
    content: TripContent,
    overrides: Map<String, String>,
    displayDays: List<DisplayDay>,
    edits: Map<String, DayEdit>,
    focus: ItineraryFocus?,
    onFocusConsumed: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val dao = remember { JournalDb.get(context).itineraryDao() }

    var editingDate by rememberSaveable { mutableStateOf<String?>(null) }
    var expandedDates by rememberSaveable { mutableStateOf(listOf<String>()) }
    var highlightId by remember { mutableStateOf<String?>(null) }
    var confirmGlobalRestore by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()

    LaunchedEffect(focus) {
        if (focus != null) {
            editingDate = null
            if (focus.date !in expandedDates) expandedDates = expandedDates + focus.date
            val dayIndex = displayDays.indexOfFirst { it.date == focus.date }
            if (dayIndex >= 0) listState.animateScrollToItem(dayIndex)
            highlightId = focus.eventId
            delay(2000)
            highlightId = null
            onFocusConsumed()
        }
    }

    val editing = editingDate?.let { date -> content.days.find { it.date == date } }
    if (editing != null) {
        BackHandler { editingDate = null }
        DayEditor(
            base = editing,
            edit = edits[editing.date],
            allDays = content.days,
            edits = edits,
            onClose = { editingDate = null }
        )
        return
    }

    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        itemsIndexed(displayDays, key = { _, d -> d.date }) { index, day ->
            ItineraryDayCard(
                day = day,
                dayNumber = index + 1,
                content = content,
                overrides = overrides,
                expanded = day.date in expandedDates,
                onToggle = {
                    expandedDates = if (day.date in expandedDates) expandedDates - day.date
                    else expandedDates + day.date
                },
                highlightId = highlightId,
                onEdit = { editingDate = day.date }
            )
        }
        if (edits.isNotEmpty()) {
            item {
                TextButton(
                    onClick = { confirmGlobalRestore = true },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Restore the whole original plan")
                }
            }
        }
    }

    if (confirmGlobalRestore) {
        AlertDialog(
            onDismissRequest = { confirmGlobalRestore = false },
            title = { Text("Restore original plan?") },
            text = { Text("Every day goes back to the bundled plan. All itinerary edits are removed. Checklists, journal, and budget are not touched.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmGlobalRestore = false
                    scope.launch { dao.restoreAll() }
                }) { Text("Restore everything") }
            },
            dismissButton = {
                TextButton(onClick = { confirmGlobalRestore = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun ItineraryDayCard(
    day: DisplayDay,
    dayNumber: Int,
    content: TripContent,
    overrides: Map<String, String>,
    expanded: Boolean,
    onToggle: () -> Unit,
    highlightId: String?,
    onEdit: () -> Unit
) {
    val pretty = DayResolver.parse(day.date).format(DateTimeFormatter.ofPattern("EEE, MMM d"))
    Card(modifier = Modifier.animateContentSize()) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClickLabel = if (expanded) "Collapse day" else "Expand day") { onToggle() }
                    .padding(16.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = "Day $dayNumber ${day.emoji}  $pretty",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.primary
                        )
                        if (day.dayModified) ModifiedDot()
                    }
                    Text(text = day.title, style = MaterialTheme.typography.titleMedium)
                    if (day.park.isNotBlank()) {
                        Text(
                            text = day.park,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                IconButton(onClick = onEdit) {
                    Icon(Icons.Filled.Edit, contentDescription = "Edit day $dayNumber")
                }
                Icon(
                    imageVector = if (expanded) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
                    contentDescription = null
                )
            }
            if (expanded) {
                Column(
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    day.events.forEach { de ->
                        EventRow(
                            event = de.event,
                            family = content.family,
                            placeholders = content.placeholders,
                            overrides = overrides,
                            modified = de.modified || de.added,
                            highlighted = highlightId == de.id
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

@Composable
private fun DayEditor(
    base: TripDay,
    edit: DayEdit?,
    allDays: List<TripDay>,
    edits: Map<String, DayEdit>,
    onClose: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val dao = remember { JournalDb.get(context).itineraryDao() }
    val working = edit ?: ItineraryLogic.seed(base)

    fun persist(updated: DayEdit) {
        scope.launch {
            if (ItineraryLogic.isIdentity(updated, base)) dao.restoreDay(base.date)
            else dao.upsert(DayOverrideRow(base.date, ItineraryLogic.encode(updated)))
        }
    }

    var formEvent by remember { mutableStateOf<EditedEvent?>(null) }
    var confirmRestoreDay by remember { mutableStateOf(false) }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "Editing ${DayResolver.parse(base.date).format(DateTimeFormatter.ofPattern("EEE, MMM d"))}",
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.weight(1f)
                )
                TextButton(onClick = onClose) { Text("Done") }
            }
        }
        item {
            // Local echo so fast typing never races the Room round trip. The
            // state resets whenever the day flips between edited and pristine.
            val stateKey = "${base.date}_${edit == null}"
            var titleText by rememberSaveable(stateKey) { mutableStateOf(working.title) }
            var emojiText by rememberSaveable(stateKey) { mutableStateOf(working.emoji) }
            var parkText by rememberSaveable(stateKey) { mutableStateOf(working.park) }
            Card {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlinedTextField(
                        value = titleText,
                        onValueChange = {
                            titleText = it
                            persist(working.copy(title = it, emoji = emojiText, park = parkText))
                        },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Day title") }
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = emojiText,
                            onValueChange = {
                                emojiText = it
                                persist(working.copy(title = titleText, emoji = it, park = parkText))
                            },
                            modifier = Modifier.weight(1f),
                            label = { Text("Emoji") }
                        )
                        OutlinedTextField(
                            value = parkText,
                            onValueChange = {
                                parkText = it
                                persist(working.copy(title = titleText, emoji = emojiText, park = it))
                            },
                            modifier = Modifier.weight(2f),
                            label = { Text("Park") }
                        )
                    }
                }
            }
        }
        itemsIndexed(working.events, key = { _, e -> e.id }) { _, ee ->
            EditorEventRow(
                ee = ee,
                base = base,
                onMoveUp = { persist(ItineraryLogic.move(working, ee.id, up = true)) },
                onMoveDown = { persist(ItineraryLogic.move(working, ee.id, up = false)) },
                onEdit = { formEvent = ee },
                onDelete = { persist(ItineraryLogic.deleteEvent(working, ee.id)) },
                onRestore = { persist(ItineraryLogic.restoreEvent(working, ee.id)) }
            )
        }
        item {
            OutlinedButton(
                onClick = {
                    formEvent = EditedEvent(
                        id = "add_" + UUID.randomUUID().toString(),
                        origIndex = null,
                        title = ""
                    )
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
            ) {
                Icon(Icons.Filled.Add, contentDescription = null)
                Spacer(modifier = Modifier.padding(start = 6.dp))
                Text("Add an event")
            }
        }
        item {
            TextButton(onClick = { confirmRestoreDay = true }, modifier = Modifier.fillMaxWidth()) {
                Text("Restore this day to the original plan")
            }
        }
    }

    formEvent?.let { fe ->
        val isNew = working.events.none { it.id == fe.id }
        EventForm(
            initial = fe,
            isNew = isNew,
            currentDate = base.date,
            allDays = allDays,
            onDismiss = { formEvent = null },
            onSave = { saved, targetDate ->
                formEvent = null
                if (targetDate != null && targetDate != base.date) {
                    // Move to another day: update source and target overrides.
                    val targetBase = allDays.find { it.date == targetDate } ?: return@EventForm
                    val targetEdit = edits[targetDate] ?: ItineraryLogic.seed(targetBase)
                    val withSaved = if (isNew) ItineraryLogic.addEvent(working, saved)
                    else ItineraryLogic.updateEvent(working, saved)
                    val (newSource, newTarget) = ItineraryLogic.moveToDay(
                        withSaved, targetEdit, saved.id, "add_" + UUID.randomUUID().toString()
                    )
                    persist(newSource)
                    scope.launch {
                        if (ItineraryLogic.isIdentity(newTarget, targetBase)) dao.restoreDay(targetDate)
                        else dao.upsert(DayOverrideRow(targetDate, ItineraryLogic.encode(newTarget)))
                    }
                } else if (isNew) {
                    persist(ItineraryLogic.addEvent(working, saved))
                } else {
                    persist(ItineraryLogic.updateEvent(working, saved))
                }
            }
        )
    }

    if (confirmRestoreDay) {
        AlertDialog(
            onDismissRequest = { confirmRestoreDay = false },
            title = { Text("Restore this day?") },
            text = { Text("All edits to this day are removed and the bundled plan comes back.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmRestoreDay = false
                    scope.launch { dao.restoreDay(base.date) }
                }) { Text("Restore day") }
            },
            dismissButton = {
                TextButton(onClick = { confirmRestoreDay = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun EditorEventRow(
    ee: EditedEvent,
    base: TripDay,
    onMoveUp: () -> Unit,
    onMoveDown: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
    onRestore: () -> Unit
) {
    Card {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = listOfNotNull(ee.time, ee.title.ifBlank { "(untitled)" }).joinToString("  "),
                        style = MaterialTheme.typography.titleSmall,
                        textDecoration = if (ee.deleted) TextDecoration.LineThrough else null,
                        color = if (ee.deleted) MaterialTheme.colorScheme.onSurfaceVariant
                        else MaterialTheme.colorScheme.onSurface
                    )
                    if (!ee.deleted && ItineraryLogic.isEventModified(ee, base)) ModifiedDot()
                }
                if (ee.deleted) {
                    TextButton(onClick = onRestore) { Text("Restore") }
                }
            }
            if (!ee.deleted) {
                IconButton(onClick = onMoveUp) {
                    Icon(Icons.Filled.KeyboardArrowUp, contentDescription = "Move up")
                }
                IconButton(onClick = onMoveDown) {
                    Icon(Icons.Filled.KeyboardArrowDown, contentDescription = "Move down")
                }
                IconButton(onClick = onEdit) {
                    Icon(Icons.Filled.Edit, contentDescription = "Edit event")
                }
                IconButton(onClick = onDelete) {
                    Icon(
                        Icons.Filled.Delete,
                        contentDescription = "Delete event",
                        tint = MaterialTheme.colorScheme.error
                    )
                }
            }
        }
    }
}

@Composable
private fun EventForm(
    initial: EditedEvent,
    isNew: Boolean,
    currentDate: String,
    allDays: List<TripDay>,
    onDismiss: () -> Unit,
    onSave: (EditedEvent, String?) -> Unit
) {
    var time by rememberSaveable(initial.id) { mutableStateOf(initial.time ?: "") }
    var title by rememberSaveable(initial.id) { mutableStateOf(initial.title) }
    var location by rememberSaveable(initial.id) { mutableStateOf(initial.location ?: "") }
    var notes by rememberSaveable(initial.id) { mutableStateOf(initial.notes ?: "") }
    var mustDo by rememberSaveable(initial.id) { mutableStateOf(initial.mustDo) }
    var heightMin by rememberSaveable(initial.id) { mutableStateOf(initial.heightMin?.toString() ?: "") }
    var heightMax by rememberSaveable(initial.id) { mutableStateOf(initial.heightMax?.toString() ?: "") }
    var targetDate by rememberSaveable(initial.id) { mutableStateOf(currentDate) }
    var dayMenuOpen by remember { mutableStateOf(false) }

    Dialog(onDismissRequest = onDismiss) {
        Card {
            Column(
                modifier = Modifier
                    .padding(16.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    text = if (isNew) "New event" else "Edit event",
                    style = MaterialTheme.typography.titleLarge
                )
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Title") }
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = time,
                        onValueChange = { time = it },
                        modifier = Modifier.weight(1f),
                        label = { Text("Time") }
                    )
                    OutlinedTextField(
                        value = location,
                        onValueChange = { location = it },
                        modifier = Modifier.weight(2f),
                        label = { Text("Location") }
                    )
                }
                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Notes / confirmation ({{TOKEN}} works here)") }
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = heightMin,
                        onValueChange = { heightMin = it.filter { c -> c.isDigit() } },
                        modifier = Modifier.weight(1f),
                        label = { Text("Min height") }
                    )
                    OutlinedTextField(
                        value = heightMax,
                        onValueChange = { heightMax = it.filter { c -> c.isDigit() } },
                        modifier = Modifier.weight(1f),
                        label = { Text("Max height") }
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(text = "Must do", modifier = Modifier.weight(1f))
                    Switch(checked = mustDo, onCheckedChange = { mustDo = it })
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(text = "Day", modifier = Modifier.weight(1f))
                    TextButton(onClick = { dayMenuOpen = true }) {
                        val d = allDays.find { it.date == targetDate }
                        Text(text = "${targetDate}  ${d?.emoji ?: ""}")
                    }
                    DropdownMenu(expanded = dayMenuOpen, onDismissRequest = { dayMenuOpen = false }) {
                        allDays.forEach { d ->
                            DropdownMenuItem(
                                text = { Text("${d.date}  ${d.emoji} ${d.title}") },
                                onClick = {
                                    targetDate = d.date
                                    dayMenuOpen = false
                                }
                            )
                        }
                    }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End
                ) {
                    TextButton(onClick = onDismiss) { Text("Cancel") }
                    Spacer(modifier = Modifier.padding(start = 8.dp))
                    Button(
                        onClick = {
                            onSave(
                                initial.copy(
                                    time = time.ifBlank { null },
                                    title = title.trim(),
                                    location = location.ifBlank { null },
                                    notes = notes.ifBlank { null },
                                    mustDo = mustDo,
                                    heightMin = heightMin.toIntOrNull(),
                                    heightMax = heightMax.toIntOrNull()
                                ),
                                targetDate.takeIf { it != currentDate }
                            )
                        },
                        enabled = title.isNotBlank()
                    ) { Text("Save") }
                }
            }
        }
    }
}
