package com.auditcompanion

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.auditcompanion.data.AppDatabase
import com.auditcompanion.data.Attachment
import com.auditcompanion.data.Audit
import com.auditcompanion.data.AuditStatus
import com.auditcompanion.data.Category
import com.auditcompanion.data.CheckItem
import com.auditcompanion.data.CheckState
import com.auditcompanion.data.Finding
import com.auditcompanion.data.Platform
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val db = AppDatabase.get(app)
    private val dao = db.auditDao()

    val audits: StateFlow<List<Audit>> = dao.observeAudits()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val categories: StateFlow<List<Category>> = dao.observeCategories()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val checks: StateFlow<List<CheckItem>> = dao.observeChecks()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val checkedCounts: Flow<Map<Long, Int>> =
        dao.observeCheckedCounts().map { list -> list.associate { it.auditId to it.cnt } }

    val findingCounts: Flow<Map<Long, Int>> =
        dao.observeFindingCounts().map { list -> list.associate { it.auditId to it.cnt } }

    fun audit(id: Long): Flow<Audit?> = dao.observeAudit(id)
    fun findings(auditId: Long): Flow<List<Finding>> = dao.observeFindings(auditId)
    fun checkStates(auditId: Long): Flow<List<CheckState>> = dao.observeCheckStates(auditId)
    fun attachments(findingId: Long): Flow<List<Attachment>> = dao.observeAttachments(findingId)

    // ---- Audits ----

    fun createAudit(
        clientName: String,
        appName: String,
        platform: Platform,
        clientContact: String = "",
        onCreated: (Long) -> Unit,
    ) {
        viewModelScope.launch {
            val id = dao.insertAudit(
                Audit(
                    clientName = clientName,
                    appName = appName,
                    platform = platform,
                    clientContact = clientContact,
                    dateStarted = System.currentTimeMillis(),
                )
            )
            onCreated(id)
        }
    }

    fun updateAudit(audit: Audit) {
        viewModelScope.launch { dao.updateAudit(audit) }
    }

    fun setStatus(audit: Audit, status: AuditStatus) {
        viewModelScope.launch {
            val deliveredAt =
                if (status == AuditStatus.DELIVERED && audit.deliveredAt == null) {
                    System.currentTimeMillis()
                } else {
                    audit.deliveredAt
                }
            dao.updateAudit(audit.copy(status = status, deliveredAt = deliveredAt))
        }
    }

    fun deleteAudit(audit: Audit) {
        viewModelScope.launch {
            dao.getAttachmentsForAudit(audit.id).forEach {
                AttachmentStore.delete(getApplication(), it.fileName)
            }
            dao.deleteAudit(audit)
        }
    }

    /**
     * Copies an audit as a fresh In Progress audit. With [reaudit] the
     * findings are copied too, titled "Verify fixed: ..." so the next pass
     * confirms each fix (photos are not copied).
     */
    fun duplicateAudit(audit: Audit, reaudit: Boolean, onCreated: (Long) -> Unit) {
        viewModelScope.launch {
            val now = System.currentTimeMillis()
            val newId = dao.insertAudit(
                audit.copy(
                    id = 0,
                    dateStarted = now,
                    status = AuditStatus.IN_PROGRESS,
                    deliveredAt = null,
                    summary = "",
                    fixOrder = "",
                )
            )
            if (reaudit) {
                dao.getFindingsList(audit.id).forEach { f ->
                    dao.insertFinding(
                        f.copy(
                            id = 0,
                            auditId = newId,
                            title = "Verify fixed: ${f.title}",
                            createdAt = now,
                        )
                    )
                }
            }
            onCreated(newId)
        }
    }

    fun setCheck(auditId: Long, checkId: Long, checked: Boolean) {
        viewModelScope.launch {
            dao.upsertCheckState(CheckState(auditId, checkId, checked))
        }
    }

    // ---- Findings ----

    suspend fun getFinding(id: Long): Finding? = dao.getFinding(id)

    /**
     * Saves a finding along with staged attachment changes: [newFiles] are
     * file names already imported into internal storage that need rows, and
     * [removed] are existing attachments to delete (row + file).
     */
    fun saveFinding(
        finding: Finding,
        newFiles: List<String> = emptyList(),
        removed: List<Attachment> = emptyList(),
        onDone: () -> Unit = {},
    ) {
        viewModelScope.launch {
            val id = if (finding.id == 0L) {
                dao.insertFinding(finding)
            } else {
                dao.updateFinding(finding)
                finding.id
            }
            newFiles.forEach { dao.insertAttachment(Attachment(findingId = id, fileName = it)) }
            removed.forEach {
                dao.deleteAttachment(it)
                AttachmentStore.delete(getApplication(), it.fileName)
            }
            onDone()
        }
    }

    fun deleteFinding(finding: Finding, onDone: () -> Unit = {}) {
        viewModelScope.launch {
            dao.getAttachments(finding.id).forEach {
                AttachmentStore.delete(getApplication(), it.fileName)
            }
            dao.deleteFinding(finding)
            onDone()
        }
    }

    // ---- Categories & checks ----

    fun createCategory(name: String, onCreated: (Long) -> Unit) {
        viewModelScope.launch {
            val nextOrder = (categories.value.maxOfOrNull { it.sortOrder } ?: -1) + 1
            val id = dao.insertCategory(
                Category(name = name, meaning = "", claudePrompt = "", sortOrder = nextOrder)
            )
            onCreated(id)
        }
    }

    fun updateCategory(category: Category) {
        viewModelScope.launch { dao.updateCategory(category) }
    }

    fun deleteCategory(category: Category) {
        viewModelScope.launch { dao.deleteCategory(category) }
    }

    /** Swaps sort order with the neighbour at [index] + [delta] in [ordered]. */
    fun moveCategory(ordered: List<Category>, index: Int, delta: Int) {
        val other = index + delta
        if (index !in ordered.indices || other !in ordered.indices) return
        val a = ordered[index]
        val b = ordered[other]
        viewModelScope.launch {
            dao.updateCategory(a.copy(sortOrder = b.sortOrder))
            dao.updateCategory(b.copy(sortOrder = a.sortOrder))
        }
    }

    fun addCheck(categoryId: Long, text: String) {
        viewModelScope.launch {
            val nextOrder = (checks.value.filter { it.categoryId == categoryId }
                .maxOfOrNull { it.sortOrder } ?: -1) + 1
            dao.insertCheck(CheckItem(categoryId = categoryId, text = text, sortOrder = nextOrder))
        }
    }

    fun updateCheck(check: CheckItem) {
        viewModelScope.launch { dao.updateCheck(check) }
    }

    fun deleteCheck(check: CheckItem) {
        viewModelScope.launch { dao.deleteCheck(check) }
    }

    fun moveCheck(ordered: List<CheckItem>, index: Int, delta: Int) {
        val other = index + delta
        if (index !in ordered.indices || other !in ordered.indices) return
        val a = ordered[index]
        val b = ordered[other]
        viewModelScope.launch {
            dao.updateCheck(a.copy(sortOrder = b.sortOrder))
            dao.updateCheck(b.copy(sortOrder = a.sortOrder))
        }
    }
}
