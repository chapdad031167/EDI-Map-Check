package com.auditcompanion.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.auditcompanion.AppViewModel
import com.auditcompanion.data.CATEGORIES
import com.auditcompanion.data.Finding
import com.auditcompanion.data.Severity

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun FindingScreen(
    viewModel: AppViewModel,
    auditId: Long,
    categoryIndex: Int,
    findingId: Long?,
    onDone: () -> Unit,
) {
    var title by remember { mutableStateOf("") }
    var category by remember { mutableStateOf(categoryIndex) }
    var severity by remember { mutableStateOf(Severity.MEDIUM) }
    var fileRef by remember { mutableStateOf("") }
    var clientNote by remember { mutableStateOf("") }
    var rawOutput by remember { mutableStateOf("") }
    var rawExpanded by remember { mutableStateOf(false) }
    var existing by remember { mutableStateOf<Finding?>(null) }
    var loaded by remember { mutableStateOf(findingId == null) }
    var confirmDelete by remember { mutableStateOf(false) }

    LaunchedEffect(findingId) {
        if (findingId != null) {
            viewModel.getFinding(findingId)?.let { f ->
                existing = f
                title = f.title
                category = f.categoryIndex
                severity = f.severity
                fileRef = f.fileRef
                clientNote = f.clientNote
                rawOutput = f.rawOutput
            }
            loaded = true
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (findingId == null) "Add Finding" else "Edit Finding") },
                navigationIcon = {
                    IconButton(onClick = onDone) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (existing != null) {
                        IconButton(onClick = { confirmDelete = true }) {
                            Icon(Icons.Default.Delete, contentDescription = "Delete finding")
                        }
                    }
                },
            )
        },
    ) { padding ->
        if (!loaded) return@Scaffold
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(
                value = title,
                onValueChange = { title = it },
                label = { Text("Short title") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            Text("Category", style = MaterialTheme.typography.labelLarge)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                CATEGORIES.forEachIndexed { i, c ->
                    FilterChip(
                        selected = category == i,
                        onClick = { category = i },
                        label = { Text(c.name) },
                    )
                }
            }

            Text("Severity", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Severity.entries.forEach { s ->
                    FilterChip(
                        selected = severity == s,
                        onClick = { severity = s },
                        label = { Text(s.label) },
                    )
                }
            }

            OutlinedTextField(
                value = fileRef,
                onValueChange = { fileRef = it },
                label = { Text("File / line reference") },
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = clientNote,
                onValueChange = { clientNote = it },
                label = { Text("What it means for the client (plain English)") },
                modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 100.dp),
            )

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "Raw Claude Code output",
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = { rawExpanded = !rawExpanded }) {
                    Icon(
                        if (rawExpanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                        contentDescription = if (rawExpanded) "Collapse" else "Expand",
                    )
                }
            }
            Text(
                "Stored for your records — excluded from the client report.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (rawExpanded) {
                OutlinedTextField(
                    value = rawOutput,
                    onValueChange = { rawOutput = it },
                    label = { Text("Paste raw output here") },
                    modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 220.dp),
                )
            }

            Spacer(Modifier.height(4.dp))
            Button(
                onClick = {
                    val base = existing
                    val finding = Finding(
                        id = base?.id ?: 0L,
                        auditId = auditId,
                        title = title.trim(),
                        categoryIndex = category,
                        severity = severity,
                        fileRef = fileRef.trim(),
                        clientNote = clientNote.trim(),
                        rawOutput = rawOutput,
                        createdAt = base?.createdAt ?: System.currentTimeMillis(),
                    )
                    viewModel.saveFinding(finding) { onDone() }
                },
                enabled = title.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Save Finding") }
        }
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete finding?") },
            text = { Text("\"$title\" will be permanently deleted.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = false
                    existing?.let { viewModel.deleteFinding(it) { onDone() } }
                }) { Text("Delete") }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = false }) { Text("Cancel") }
            },
        )
    }
}
