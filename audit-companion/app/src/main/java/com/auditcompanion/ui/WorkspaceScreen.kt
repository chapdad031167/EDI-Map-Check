package com.auditcompanion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.auditcompanion.AppViewModel
import com.auditcompanion.data.Audit
import com.auditcompanion.data.AuditStatus
import com.auditcompanion.data.Category
import com.auditcompanion.data.CheckItem
import com.auditcompanion.data.Finding
import com.auditcompanion.data.Platform

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkspaceScreen(
    viewModel: AppViewModel,
    auditId: Long,
    onBack: () -> Unit,
    onAddFinding: (categoryId: Long) -> Unit,
    onEditFinding: (Finding) -> Unit,
    onOpenReport: () -> Unit,
) {
    val auditFlow = remember(auditId) { viewModel.audit(auditId) }
    val findingsFlow = remember(auditId) { viewModel.findings(auditId) }
    val checkStatesFlow = remember(auditId) { viewModel.checkStates(auditId) }
    val audit by auditFlow.collectAsStateWithLifecycle(null)
    val findings by findingsFlow.collectAsStateWithLifecycle(emptyList())
    val checkStates by checkStatesFlow.collectAsStateWithLifecycle(emptyList())
    val categories by viewModel.categories.collectAsStateWithLifecycle()
    val allChecks by viewModel.checks.collectAsStateWithLifecycle()

    val currentAudit = audit ?: return
    val checkedMap = remember(checkStates) {
        checkStates.associate { it.checkId to it.checked }
    }
    val checksByCategory = remember(allChecks) { allChecks.groupBy { it.categoryId } }

    var statusMenuOpen by remember { mutableStateOf(false) }
    var overflowOpen by remember { mutableStateOf(false) }
    var showEditDetails by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(currentAudit.appName, style = MaterialTheme.typography.titleMedium)
                        Text(
                            currentAudit.clientName,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    TextButton(onClick = { statusMenuOpen = true }) {
                        Text(currentAudit.status.label)
                        Icon(Icons.Default.ArrowDropDown, contentDescription = "Change status")
                    }
                    DropdownMenu(
                        expanded = statusMenuOpen,
                        onDismissRequest = { statusMenuOpen = false },
                    ) {
                        AuditStatus.entries.forEach { s ->
                            DropdownMenuItem(
                                text = { Text(s.label) },
                                onClick = {
                                    statusMenuOpen = false
                                    viewModel.setStatus(currentAudit, s)
                                },
                            )
                        }
                    }
                    IconButton(onClick = onOpenReport) {
                        Icon(Icons.Default.Description, contentDescription = "Report")
                    }
                    IconButton(onClick = { overflowOpen = true }) {
                        Icon(Icons.Default.MoreVert, contentDescription = "More options")
                    }
                    DropdownMenu(
                        expanded = overflowOpen,
                        onDismissRequest = { overflowOpen = false },
                    ) {
                        DropdownMenuItem(
                            text = { Text("Edit details") },
                            onClick = {
                                overflowOpen = false
                                showEditDetails = true
                            },
                        )
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            categories.forEachIndexed { index, category ->
                item(key = "cat-${category.id}") {
                    CategorySection(
                        number = index + 1,
                        category = category,
                        checks = checksByCategory[category.id].orEmpty(),
                        checkedMap = checkedMap,
                        findings = findings.filter { it.categoryId == category.id },
                        onCheck = { checkId, checked ->
                            viewModel.setCheck(auditId, checkId, checked)
                        },
                        onAddFinding = { onAddFinding(category.id) },
                        onEditFinding = onEditFinding,
                    )
                }
            }
        }
    }

    if (showEditDetails) {
        EditDetailsDialog(
            audit = currentAudit,
            onDismiss = { showEditDetails = false },
            onSave = { updated ->
                showEditDetails = false
                viewModel.updateAudit(updated)
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun EditDetailsDialog(
    audit: Audit,
    onDismiss: () -> Unit,
    onSave: (Audit) -> Unit,
) {
    var client by remember { mutableStateOf(audit.clientName) }
    var app by remember { mutableStateOf(audit.appName) }
    var contact by remember { mutableStateOf(audit.clientContact) }
    var platform by remember { mutableStateOf(audit.platform) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit details") },
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
                    label = { Text("Client contact") },
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
                audit.deliveredAt?.let {
                    Text(
                        "Delivered ${formatDate(it)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onSave(
                        audit.copy(
                            clientName = client.trim(),
                            appName = app.trim(),
                            clientContact = contact.trim(),
                            platform = platform,
                        )
                    )
                },
                enabled = client.isNotBlank() && app.isNotBlank(),
            ) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun CategorySection(
    number: Int,
    category: Category,
    checks: List<CheckItem>,
    checkedMap: Map<Long, Boolean>,
    findings: List<Finding>,
    onCheck: (checkId: Long, checked: Boolean) -> Unit,
    onAddFinding: () -> Unit,
    onEditFinding: (Finding) -> Unit,
) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("$number. ${category.name}", style = MaterialTheme.typography.titleMedium)
            if (category.meaning.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    category.meaning,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(8.dp))

            checks.forEach { check ->
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Checkbox(
                        checked = checkedMap[check.id] ?: false,
                        onCheckedChange = { onCheck(check.id, it) },
                    )
                    Text(check.text, style = MaterialTheme.typography.bodyMedium)
                }
            }

            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (category.claudePrompt.isNotBlank()) {
                    OutlinedButton(onClick = {
                        copyToClipboard(context, clipboard, category.claudePrompt, "Prompt")
                    }) {
                        Icon(
                            Icons.Default.ContentCopy,
                            contentDescription = null,
                            modifier = Modifier.width(18.dp),
                        )
                        Spacer(Modifier.width(6.dp))
                        Text("Copy prompt")
                    }
                }
                Button(onClick = onAddFinding) {
                    Icon(
                        Icons.Default.Add,
                        contentDescription = null,
                        modifier = Modifier.width(18.dp),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text("Add Finding")
                }
            }

            if (findings.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                HorizontalDivider()
                findings.forEach { finding ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onEditFinding(finding) }
                            .padding(vertical = 8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            finding.title,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                        Spacer(Modifier.width(8.dp))
                        SeverityBadge(finding.severity)
                    }
                }
            }
        }
    }
}
