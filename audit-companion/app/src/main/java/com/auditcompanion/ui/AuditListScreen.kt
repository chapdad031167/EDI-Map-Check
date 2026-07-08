package com.auditcompanion.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.IconButton
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.HorizontalDivider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.auditcompanion.AppViewModel
import com.auditcompanion.data.Audit
import com.auditcompanion.data.Platform

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun AuditListScreen(
    viewModel: AppViewModel,
    onOpenAudit: (Long) -> Unit,
    onManageCategories: () -> Unit,
) {
    val audits by viewModel.audits.collectAsStateWithLifecycle()
    var showNewDialog by remember { mutableStateOf(false) }
    var auditToDelete by remember { mutableStateOf<Audit?>(null) }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = { Text("Audit Companion") },
                actions = {
                    IconButton(onClick = onManageCategories) {
                        Icon(
                            Icons.Default.Checklist,
                            contentDescription = "Manage categories",
                        )
                    }
                },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { showNewDialog = true },
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("New Audit") },
            )
        },
    ) { padding ->
        if (audits.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text(
                    "No audits yet.\nTap New Audit to start one.",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    start = 16.dp, end = 16.dp, top = 8.dp, bottom = 96.dp
                ),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(audits, key = { it.id }) { audit ->
                    AuditCard(
                        audit = audit,
                        onClick = { onOpenAudit(audit.id) },
                        onLongClick = { auditToDelete = audit },
                    )
                }
            }
        }
    }

    if (showNewDialog) {
        NewAuditDialog(
            onDismiss = { showNewDialog = false },
            onCreate = { client, app, platform ->
                showNewDialog = false
                viewModel.createAudit(client, app, platform) { id -> onOpenAudit(id) }
            },
        )
    }

    auditToDelete?.let { audit ->
        AlertDialog(
            onDismissRequest = { auditToDelete = null },
            title = { Text("Delete audit?") },
            text = {
                Text(
                    "\"${audit.clientName} — ${audit.appName}\" and all of its findings " +
                        "will be permanently deleted."
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.deleteAudit(audit)
                    auditToDelete = null
                }) { Text("Delete") }
            },
            dismissButton = {
                TextButton(onClick = { auditToDelete = null }) { Text("Cancel") }
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun AuditCard(audit: Audit, onClick: () -> Unit, onLongClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick, onLongClick = onLongClick),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(audit.clientName, style = MaterialTheme.typography.titleMedium)
                AssistChip(onClick = {}, label = { Text(audit.status.label) })
            }
            Spacer(Modifier.height(4.dp))
            Text(audit.appName, style = MaterialTheme.typography.bodyLarge)
            Spacer(Modifier.height(6.dp))
            HorizontalDivider()
            Spacer(Modifier.height(6.dp))
            Text(
                "${audit.platform.label}  •  Started ${formatDate(audit.dateStarted)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun NewAuditDialog(
    onDismiss: () -> Unit,
    onCreate: (client: String, app: String, platform: Platform) -> Unit,
) {
    var client by remember { mutableStateOf("") }
    var app by remember { mutableStateOf("") }
    var platform by remember { mutableStateOf(Platform.LOVABLE) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New Audit") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = client,
                    onValueChange = { client = it },
                    label = { Text("Client name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = app,
                    onValueChange = { app = it },
                    label = { Text("App name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text("Platform used", style = MaterialTheme.typography.labelLarge)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Platform.entries.forEach { p ->
                        FilterChip(
                            selected = platform == p,
                            onClick = { platform = p },
                            label = { Text(p.label) },
                        )
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onCreate(client.trim(), app.trim(), platform) },
                enabled = client.isNotBlank() && app.isNotBlank(),
            ) { Text("Create") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
