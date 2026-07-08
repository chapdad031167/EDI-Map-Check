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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.auditcompanion.AppViewModel
import com.auditcompanion.data.CheckItem
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CategoryEditScreen(
    viewModel: AppViewModel,
    categoryId: Long,
    onBack: () -> Unit,
) {
    val categories by viewModel.categories.collectAsStateWithLifecycle()
    val allChecks by viewModel.checks.collectAsStateWithLifecycle()
    val category = categories.firstOrNull { it.id == categoryId } ?: return
    val checks = allChecks.filter { it.categoryId == categoryId }

    var name by remember(category.id) { mutableStateOf(category.name) }
    var meaning by remember(category.id) { mutableStateOf(category.meaning) }
    var prompt by remember(category.id) { mutableStateOf(category.claudePrompt) }
    var confirmDelete by remember { mutableStateOf(false) }
    var checkBeingEdited by remember { mutableStateOf<CheckItem?>(null) }
    var showAddCheck by remember { mutableStateOf(false) }

    // Auto-save text edits after a short pause in typing.
    LaunchedEffect(name, meaning, prompt) {
        delay(400)
        if (name != category.name || meaning != category.meaning ||
            prompt != category.claudePrompt
        ) {
            viewModel.updateCategory(
                category.copy(name = name.trim(), meaning = meaning, claudePrompt = prompt)
            )
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Edit Category") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = { confirmDelete = true }) {
                        Icon(Icons.Default.Delete, contentDescription = "Delete category")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text("Name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = meaning,
                onValueChange = { meaning = it },
                label = { Text("Plain-language meaning") },
                modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 80.dp),
            )
            OutlinedTextField(
                value = prompt,
                onValueChange = { prompt = it },
                label = { Text("Claude Code inspection prompt") },
                modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 120.dp),
            )

            Text("Checks", style = MaterialTheme.typography.titleSmall)
            checks.forEachIndexed { index, check ->
                Card(Modifier.fillMaxWidth()) {
                    Row(
                        Modifier.fillMaxWidth().padding(start = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            check.text,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f).padding(vertical = 12.dp),
                        )
                        IconButton(
                            onClick = { viewModel.moveCheck(checks, index, -1) },
                            enabled = index > 0,
                        ) {
                            Icon(Icons.Default.ArrowUpward, contentDescription = "Move up")
                        }
                        IconButton(
                            onClick = { viewModel.moveCheck(checks, index, 1) },
                            enabled = index < checks.lastIndex,
                        ) {
                            Icon(Icons.Default.ArrowDownward, contentDescription = "Move down")
                        }
                        IconButton(onClick = { checkBeingEdited = check }) {
                            Icon(Icons.Default.Edit, contentDescription = "Edit check")
                        }
                        IconButton(onClick = { viewModel.deleteCheck(check) }) {
                            Icon(Icons.Default.Delete, contentDescription = "Delete check")
                        }
                    }
                }
            }
            OutlinedButton(onClick = { showAddCheck = true }) {
                Icon(Icons.Default.Add, contentDescription = null)
                Text("Add check")
            }
            Spacer(Modifier.height(24.dp))
        }
    }

    if (showAddCheck) {
        CheckTextDialog(
            title = "New check",
            initial = "",
            onDismiss = { showAddCheck = false },
            onSave = { text ->
                showAddCheck = false
                viewModel.addCheck(categoryId, text)
            },
        )
    }

    checkBeingEdited?.let { check ->
        CheckTextDialog(
            title = "Edit check",
            initial = check.text,
            onDismiss = { checkBeingEdited = null },
            onSave = { text ->
                checkBeingEdited = null
                viewModel.updateCheck(check.copy(text = text))
            },
        )
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete category?") },
            text = {
                Text(
                    "\"${category.name}\" and its checks will be deleted from every audit. " +
                        "Findings already filed under it are kept but lose the category label."
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = false
                    viewModel.deleteCategory(category)
                    onBack()
                }) { Text("Delete") }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = false }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun CheckTextDialog(
    title: String,
    initial: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit,
) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text("Check description") },
                modifier = Modifier.fillMaxWidth(),
            )
        },
        confirmButton = {
            Button(onClick = { onSave(text.trim()) }, enabled = text.isNotBlank()) {
                Text("Save")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
