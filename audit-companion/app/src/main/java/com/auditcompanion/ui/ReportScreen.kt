package com.auditcompanion.ui

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.auditcompanion.AppViewModel
import com.auditcompanion.buildReportMarkdown
import com.auditcompanion.categoryName
import com.auditcompanion.data.Audit
import com.auditcompanion.data.Finding
import com.auditcompanion.defaultFixOrder
import com.auditcompanion.sortedWorstFirst
import com.auditcompanion.todayFormatted
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportScreen(
    viewModel: AppViewModel,
    auditId: Long,
    onBack: () -> Unit,
) {
    val audit by viewModel.audit(auditId).collectAsStateWithLifecycle(null)
    val findings by viewModel.findings(auditId).collectAsStateWithLifecycle(emptyList())

    val currentAudit = audit ?: return
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current

    // Editable report fields, initialized once from the stored audit.
    var preparedBy by remember(currentAudit.id) { mutableStateOf(currentAudit.preparedBy) }
    var summary by remember(currentAudit.id) { mutableStateOf(currentAudit.summary) }
    var fixOrder by remember(currentAudit.id, findings.isNotEmpty()) {
        mutableStateOf(currentAudit.fixOrder.ifBlank { defaultFixOrder(findings) })
    }
    var whatICanFix by remember(currentAudit.id) { mutableStateOf(currentAudit.whatICanFix) }
    var nextStep by remember(currentAudit.id) { mutableStateOf(currentAudit.nextStep) }

    fun editedAudit(): Audit = currentAudit.copy(
        preparedBy = preparedBy,
        summary = summary,
        fixOrder = fixOrder,
        whatICanFix = whatICanFix,
        nextStep = nextStep,
    )

    // Auto-save edits after a short pause in typing.
    LaunchedEffect(preparedBy, summary, fixOrder, whatICanFix, nextStep) {
        delay(400)
        viewModel.updateAudit(editedAudit())
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Client Report") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = {
                        copyToClipboard(
                            context, clipboard,
                            buildReportMarkdown(editedAudit(), findings),
                            "Report",
                        )
                    }) {
                        Icon(Icons.Default.ContentCopy, contentDescription = "Copy report")
                    }
                    IconButton(onClick = {
                        val markdown = buildReportMarkdown(editedAudit(), findings)
                        val intent = Intent(Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(
                                Intent.EXTRA_SUBJECT,
                                "AI App Health Check: ${currentAudit.appName}",
                            )
                            putExtra(Intent.EXTRA_TEXT, markdown)
                        }
                        context.startActivity(Intent.createChooser(intent, "Share report"))
                    }) {
                        Icon(Icons.Default.Share, contentDescription = "Share report")
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
            Text("Edit report fields", style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(
                value = preparedBy,
                onValueChange = { preparedBy = it },
                label = { Text("Prepared by") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = summary,
                onValueChange = { summary = it },
                label = { Text("Summary (2 to 3 sentences)") },
                modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 90.dp),
            )
            OutlinedTextField(
                value = fixOrder,
                onValueChange = { fixOrder = it },
                label = { Text("Recommended fix order") },
                modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 90.dp),
            )
            OutlinedTextField(
                value = whatICanFix,
                onValueChange = { whatICanFix = it },
                label = { Text("What I can fix for you") },
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = nextStep,
                onValueChange = { nextStep = it },
                label = { Text("Next step") },
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(4.dp))
            Text("Preview", style = MaterialTheme.typography.titleSmall)
            ReportPreview(
                audit = editedAudit(),
                findings = findings,
                fixOrderText = fixOrder,
            )
        }
    }
}

@Composable
private fun ReportPreview(audit: Audit, findings: List<Finding>, fixOrderText: String) {
    val sorted = sortedWorstFirst(findings)

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                "AI App Health Check: ${audit.appName}",
                style = MaterialTheme.typography.titleLarge,
            )
            Text(
                "Prepared by: ${audit.preparedBy.ifBlank { "[My Name]" }}  |  Date: ${todayFormatted()}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            HorizontalDivider()

            LabeledBlock("Summary", audit.summary.ifBlank { "(add a 2 to 3 sentence summary)" })

            Text("Findings, worst first:", fontWeight = FontWeight.Bold)
            if (sorted.isEmpty()) {
                Text(
                    "(no findings yet)",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                sorted.forEachIndexed { i, f ->
                    Column(Modifier.fillMaxWidth()) {
                        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                            Text(
                                "${i + 1}. ${f.title}",
                                fontWeight = FontWeight.SemiBold,
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.weight(1f),
                            )
                            Spacer(Modifier.width(8.dp))
                            SeverityBadge(f.severity)
                        }
                        Text(
                            categoryName(f.categoryIndex),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (f.clientNote.isNotBlank()) {
                            Text(f.clientNote, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }

            LabeledBlock("Recommended fix order", fixOrderText.ifBlank { "(no findings yet)" })
            LabeledBlock("What I can fix for you", audit.whatICanFix)
            LabeledBlock("Next step", audit.nextStep)
        }
    }
}

@Composable
private fun LabeledBlock(label: String, body: String) {
    Column {
        Text("$label:", fontWeight = FontWeight.Bold)
        Text(body, style = MaterialTheme.typography.bodyMedium)
    }
}
