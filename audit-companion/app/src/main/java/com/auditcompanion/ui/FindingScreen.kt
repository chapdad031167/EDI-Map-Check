package com.auditcompanion.ui

import android.graphics.Bitmap
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.AutoFixHigh
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
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
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.foundation.clickable
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.auditcompanion.AppViewModel
import com.auditcompanion.AttachmentStore
import com.auditcompanion.data.Attachment
import com.auditcompanion.data.Finding
import com.auditcompanion.data.Severity
import com.auditcompanion.parseClaudeOutput
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun FindingScreen(
    viewModel: AppViewModel,
    auditId: Long,
    categoryId: Long,
    findingId: Long?,
    onDone: () -> Unit,
) {
    val context = LocalContext.current
    val categories by viewModel.categories.collectAsStateWithLifecycle()
    val attachmentsFlow = remember(findingId) { viewModel.attachments(findingId ?: -1L) }
    val existingAttachments by attachmentsFlow.collectAsStateWithLifecycle(emptyList())

    var title by remember { mutableStateOf("") }
    var category by remember { mutableStateOf(categoryId) }
    var severity by remember { mutableStateOf(Severity.MEDIUM) }
    var fileRef by remember { mutableStateOf("") }
    var clientNote by remember { mutableStateOf("") }
    var rawOutput by remember { mutableStateOf("") }
    var rawExpanded by remember { mutableStateOf(false) }
    var existing by remember { mutableStateOf<Finding?>(null) }
    var loaded by remember { mutableStateOf(findingId == null) }
    var confirmDelete by remember { mutableStateOf(false) }

    // Attachment staging: new files are imported to disk immediately but only
    // get database rows on save; removals of existing rows also apply on save.
    val stagedNewFiles = remember { mutableStateListOf<String>() }
    val removedAttachments = remember { mutableStateListOf<Attachment>() }
    var viewerFile by remember { mutableStateOf<String?>(null) }

    val pickImage = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        if (uri != null) {
            runCatching { AttachmentStore.import(context, uri) }
                .onSuccess { stagedNewFiles.add(it) }
        }
    }

    fun cancelAndLeave() {
        stagedNewFiles.forEach { AttachmentStore.delete(context, it) }
        onDone()
    }

    BackHandler { cancelAndLeave() }

    LaunchedEffect(findingId) {
        if (findingId != null) {
            viewModel.getFinding(findingId)?.let { f ->
                existing = f
                title = f.title
                category = f.categoryId
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
                    IconButton(onClick = { cancelAndLeave() }) {
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
                categories.forEach { c ->
                    FilterChip(
                        selected = category == c.id,
                        onClick = { category = c.id },
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

            // Photos
            Text("Photos", style = MaterialTheme.typography.labelLarge)
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                existingAttachments
                    .filter { att -> removedAttachments.none { it.id == att.id } }
                    .forEach { att ->
                        AttachmentThumb(
                            fileName = att.fileName,
                            onView = { viewerFile = att.fileName },
                            onRemove = { removedAttachments.add(att) },
                        )
                    }
                stagedNewFiles.forEach { fileName ->
                    AttachmentThumb(
                        fileName = fileName,
                        onView = { viewerFile = fileName },
                        onRemove = {
                            stagedNewFiles.remove(fileName)
                            AttachmentStore.delete(context, fileName)
                        },
                    )
                }
                OutlinedButton(onClick = {
                    pickImage.launch(
                        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                    )
                }) {
                    Icon(
                        Icons.Default.AddPhotoAlternate,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.size(6.dp))
                    Text("Add photo")
                }
            }
            Text(
                "Photos stay on this device for your records — never in the client report.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            // Raw output
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
            OutlinedButton(
                onClick = {
                    val parsed = parseClaudeOutput(rawOutput)
                    if (title.isBlank() && parsed.title != null) title = parsed.title
                    if (fileRef.isBlank() && parsed.fileRef != null) fileRef = parsed.fileRef
                    if (parsed.severity != null) severity = parsed.severity
                },
                enabled = rawOutput.isNotBlank(),
            ) {
                Icon(
                    Icons.Default.AutoFixHigh,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.size(6.dp))
                Text("Parse into fields")
            }
            Text(
                "Fills the empty fields above (title, severity, file reference) from the pasted output.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(4.dp))
            Button(
                onClick = {
                    val base = existing
                    val finding = Finding(
                        id = base?.id ?: 0L,
                        auditId = auditId,
                        title = title.trim(),
                        categoryId = category,
                        severity = severity,
                        fileRef = fileRef.trim(),
                        clientNote = clientNote.trim(),
                        rawOutput = rawOutput,
                        createdAt = base?.createdAt ?: System.currentTimeMillis(),
                    )
                    viewModel.saveFinding(
                        finding,
                        newFiles = stagedNewFiles.toList(),
                        removed = removedAttachments.toList(),
                    ) { onDone() }
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
            text = { Text("\"$title\" and its photos will be permanently deleted.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = false
                    stagedNewFiles.forEach { AttachmentStore.delete(context, it) }
                    existing?.let { viewModel.deleteFinding(it) { onDone() } }
                }) { Text("Delete") }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = false }) { Text("Cancel") }
            },
        )
    }

    viewerFile?.let { fileName ->
        Dialog(onDismissRequest = { viewerFile = null }) {
            val bitmap by produceState<Bitmap?>(null, fileName) {
                value = withContext(Dispatchers.IO) {
                    AttachmentStore.loadBitmap(context, fileName, 1600)
                }
            }
            bitmap?.let {
                Image(
                    bitmap = it.asImageBitmap(),
                    contentDescription = "Attached photo",
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .clickable { viewerFile = null },
                    contentScale = ContentScale.FillWidth,
                )
            }
        }
    }
}

@Composable
private fun AttachmentThumb(
    fileName: String,
    onView: () -> Unit,
    onRemove: () -> Unit,
) {
    val context = LocalContext.current
    val bitmap by produceState<Bitmap?>(null, fileName) {
        value = withContext(Dispatchers.IO) {
            AttachmentStore.loadBitmap(context, fileName, 256)
        }
    }
    Box(Modifier.size(84.dp)) {
        bitmap?.let {
            Image(
                bitmap = it.asImageBitmap(),
                contentDescription = "Attached photo",
                modifier = Modifier
                    .fillMaxSize()
                    .clip(RoundedCornerShape(10.dp))
                    .clickable { onView() },
                contentScale = ContentScale.Crop,
            )
        }
        FilledIconButton(
            onClick = onRemove,
            modifier = Modifier.size(24.dp).align(Alignment.TopEnd),
        ) {
            Icon(
                Icons.Default.Close,
                contentDescription = "Remove photo",
                modifier = Modifier.size(14.dp),
            )
        }
    }
}
