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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Description
import androidx.compose.material3.Button
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
import com.auditcompanion.data.AuditStatus
import com.auditcompanion.data.CATEGORIES
import com.auditcompanion.data.Finding

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkspaceScreen(
    viewModel: AppViewModel,
    auditId: Long,
    onBack: () -> Unit,
    onAddFinding: (categoryIndex: Int) -> Unit,
    onEditFinding: (Finding) -> Unit,
    onOpenReport: () -> Unit,
) {
    val audit by viewModel.audit(auditId).collectAsStateWithLifecycle(null)
    val findings by viewModel.findings(auditId).collectAsStateWithLifecycle(emptyList())
    val checkStates by viewModel.checkStates(auditId).collectAsStateWithLifecycle(emptyList())

    val currentAudit = audit ?: return
    val checkedMap = remember(checkStates) {
        checkStates.associate { (it.categoryIndex to it.checkIndex) to it.checked }
    }

    var statusMenuOpen by remember { mutableStateOf(false) }

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
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            CATEGORIES.forEachIndexed { categoryIndex, category ->
                item(key = "cat-$categoryIndex") {
                    CategorySection(
                        number = categoryIndex + 1,
                        categoryIndex = categoryIndex,
                        checkedMap = checkedMap,
                        findings = findings.filter { it.categoryIndex == categoryIndex },
                        onCheck = { checkIndex, checked ->
                            viewModel.setCheck(auditId, categoryIndex, checkIndex, checked)
                        },
                        onAddFinding = { onAddFinding(categoryIndex) },
                        onEditFinding = onEditFinding,
                    )
                }
            }
        }
    }
}

@Composable
private fun CategorySection(
    number: Int,
    categoryIndex: Int,
    checkedMap: Map<Pair<Int, Int>, Boolean>,
    findings: List<Finding>,
    onCheck: (checkIndex: Int, checked: Boolean) -> Unit,
    onAddFinding: () -> Unit,
    onEditFinding: (Finding) -> Unit,
) {
    val category = CATEGORIES[categoryIndex]
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("$number. ${category.name}", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                category.meaning,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))

            category.checks.forEachIndexed { checkIndex, check ->
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Checkbox(
                        checked = checkedMap[categoryIndex to checkIndex] ?: false,
                        onCheckedChange = { onCheck(checkIndex, it) },
                    )
                    Text(check, style = MaterialTheme.typography.bodyMedium)
                }
            }

            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
