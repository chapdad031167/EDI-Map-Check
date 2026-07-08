package com.auditcompanion.ui

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricManager
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.auditcompanion.AppViewModel
import com.auditcompanion.PREFS_NAME
import com.auditcompanion.PREF_APP_LOCK
import com.auditcompanion.data.Audit
import com.auditcompanion.data.Platform

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun AuditListScreen(
    viewModel: AppViewModel,
    onOpenAudit: (Long) -> Unit,
    onManageCategories: () -> Unit,
) {
    val context = LocalContext.current
    val audits by viewModel.audits.collectAsStateWithLifecycle()
    val allChecks by viewModel.checks.collectAsStateWithLifecycle()
    val checkedCounts by viewModel.checkedCounts.collectAsStateWithLifecycle(emptyMap())
    val findingCounts by viewModel.findingCounts.collectAsStateWithLifecycle(emptyMap())
    var showNewDialog by remember { mutableStateOf(false) }
    var auditForActions by remember { mutableStateOf<Audit?>(null) }
    var auditToDelete by remember { mutableStateOf<Audit?>(null) }
    var overflowOpen by remember { mutableStateOf(false) }
    var confirmImport by remember { mutableStateOf(false) }
    var appLockEnabled by remember {
        mutableStateOf(
            context.getSharedPreferences(PREFS_NAME, 0).getBoolean(PREF_APP_LOCK, false)
        )
    }

    val exportLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/zip")
    ) { uri ->
        if (uri != null) {
            viewModel.exportBackup(uri) { error ->
                Toast.makeText(
                    context,
                    error?.let { "Export failed: $it" } ?: "Backup exported",
                    Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    val importLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            viewModel.importBackup(uri) { error ->
                Toast.makeText(
                    context,
                    error?.let { "Import failed: $it" } ?: "Backup imported",
                    Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    fun toggleAppLock() {
        if (!appLockEnabled) {
            val authenticators = BiometricManager.Authenticators.BIOMETRIC_WEAK or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
            if (BiometricManager.from(context).canAuthenticate(authenticators) !=
                BiometricManager.BIOMETRIC_SUCCESS
            ) {
                Toast.makeText(
                    context,
                    "Set up a screen lock or fingerprint on this phone first",
                    Toast.LENGTH_LONG,
                ).show()
                return
            }
        }
        appLockEnabled = !appLockEnabled
        context.getSharedPreferences(PREFS_NAME, 0).edit()
            .putBoolean(PREF_APP_LOCK, appLockEnabled).apply()
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = { Text("Audit Companion") },
                actions = {
                    IconButton(onClick = onManageCategories) {
                        Icon(Icons.Default.Checklist, contentDescription = "Manage categories")
                    }
                    IconButton(onClick = { overflowOpen = true }) {
                        Icon(Icons.Default.MoreVert, contentDescription = "More options")
                    }
                    DropdownMenu(
                        expanded = overflowOpen,
                        onDismissRequest = { overflowOpen = false },
                    ) {
                        DropdownMenuItem(
                            text = { Text("Export backup") },
                            onClick = {
                                overflowOpen = false
                                exportLauncher.launch("audit-companion-backup.zip")
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Import backup…") },
                            onClick = {
                                overflowOpen = false
                                confirmImport = true
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("App lock") },
                            leadingIcon = {
                                Icon(Icons.Default.Lock, contentDescription = null)
                            },
                            trailingIcon = {
                                Checkbox(
                                    checked = appLockEnabled,
                                    onCheckedChange = null,
                                )
                            },
                            onClick = {
                                overflowOpen = false
                                toggleAppLock()
                            },
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
                contentPadding = PaddingValues(
                    start = 16.dp, end = 16.dp, top = 8.dp, bottom = 96.dp
                ),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(audits, key = { it.id }) { audit ->
                    AuditCard(
                        audit = audit,
                        totalChecks = allChecks.size,
                        checkedCount = checkedCounts[audit.id] ?: 0,
                        findingCount = findingCounts[audit.id] ?: 0,
                        onClick = { onOpenAudit(audit.id) },
                        onLongClick = { auditForActions = audit },
                    )
                }
            }
        }
    }

    if (showNewDialog) {
        NewAuditDialog(
            onDismiss = { showNewDialog = false },
            onCreate = { client, app, platform, contact ->
                showNewDialog = false
                viewModel.createAudit(client, app, platform, contact) { id -> onOpenAudit(id) }
            },
        )
    }

    auditForActions?.let { audit ->
        AlertDialog(
            onDismissRequest = { auditForActions = null },
            title = { Text("${audit.clientName} — ${audit.appName}") },
            text = {
                Column {
                    DropdownMenuItem(
                        text = { Text("Duplicate (fresh audit, same client)") },
                        leadingIcon = {
                            Icon(Icons.Default.ContentCopy, contentDescription = null)
                        },
                        onClick = {
                            auditForActions = null
                            viewModel.duplicateAudit(audit, reaudit = false) { onOpenAudit(it) }
                        },
                    )
                    DropdownMenuItem(
                        text = { Text("Re-audit (copies findings as \"Verify fixed\")") },
                        leadingIcon = {
                            Icon(Icons.Default.Refresh, contentDescription = null)
                        },
                        onClick = {
                            auditForActions = null
                            viewModel.duplicateAudit(audit, reaudit = true) { onOpenAudit(it) }
                        },
                    )
                    DropdownMenuItem(
                        text = { Text("Delete…") },
                        leadingIcon = {
                            Icon(Icons.Default.Delete, contentDescription = null)
                        },
                        onClick = {
                            auditToDelete = audit
                            auditForActions = null
                        },
                    )
                }
            },
            confirmButton = {},
            dismissButton = {
                TextButton(onClick = { auditForActions = null }) { Text("Cancel") }
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

    if (confirmImport) {
        AlertDialog(
            onDismissRequest = { confirmImport = false },
            title = { Text("Import backup?") },
            text = {
                Text(
                    "Importing replaces EVERYTHING currently in the app — all audits, " +
                        "findings, photos, and categories — with the backup's contents."
                )
            },
            confirmButton = {
                Button(onClick = {
                    confirmImport = false
                    importLauncher.launch(
                        arrayOf("application/zip", "application/octet-stream")
                    )
                }) { Text("Choose backup file") }
            },
            dismissButton = {
                TextButton(onClick = { confirmImport = false }) { Text("Cancel") }
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun AuditCard(
    audit: Audit,
    totalChecks: Int,
    checkedCount: Int,
    findingCount: Int,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
) {
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
                "${audit.platform.label}  •  Started ${formatDate(audit.dateStarted)}" +
                    (audit.deliveredAt?.let { "  •  Delivered ${formatDate(it)}" } ?: ""),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                "$checkedCount/$totalChecks checks  •  $findingCount " +
                    if (findingCount == 1) "finding" else "findings",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun NewAuditDialog(
    onDismiss: () -> Unit,
    onCreate: (client: String, app: String, platform: Platform, contact: String) -> Unit,
) {
    var client by remember { mutableStateOf("") }
    var app by remember { mutableStateOf("") }
    var contact by remember { mutableStateOf("") }
    var platform by remember { mutableStateOf(Platform.LOVABLE) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New Audit") },
        text = {
            Column(
                verticalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier.verticalScroll(rememberScrollState()),
            ) {
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
                OutlinedTextField(
                    value = contact,
                    onValueChange = { contact = it },
                    label = { Text("Client contact (optional)") },
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
                onClick = { onCreate(client.trim(), app.trim(), platform, contact.trim()) },
                enabled = client.isNotBlank() && app.isNotBlank(),
            ) { Text("Create") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
