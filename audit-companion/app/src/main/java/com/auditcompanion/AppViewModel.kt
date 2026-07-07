package com.auditcompanion

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.auditcompanion.data.AppDatabase
import com.auditcompanion.data.Audit
import com.auditcompanion.data.AuditStatus
import com.auditcompanion.data.CheckState
import com.auditcompanion.data.Finding
import com.auditcompanion.data.Platform
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val dao = AppDatabase.get(app).auditDao()

    val audits: StateFlow<List<Audit>> = dao.observeAudits()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    fun audit(id: Long): Flow<Audit?> = dao.observeAudit(id)
    fun findings(auditId: Long): Flow<List<Finding>> = dao.observeFindings(auditId)
    fun checkStates(auditId: Long): Flow<List<CheckState>> = dao.observeCheckStates(auditId)

    fun createAudit(
        clientName: String,
        appName: String,
        platform: Platform,
        onCreated: (Long) -> Unit,
    ) {
        viewModelScope.launch {
            val id = dao.insertAudit(
                Audit(
                    clientName = clientName,
                    appName = appName,
                    platform = platform,
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
        viewModelScope.launch { dao.updateAudit(audit.copy(status = status)) }
    }

    fun deleteAudit(audit: Audit) {
        viewModelScope.launch { dao.deleteAudit(audit) }
    }

    fun setCheck(auditId: Long, categoryIndex: Int, checkIndex: Int, checked: Boolean) {
        viewModelScope.launch {
            dao.upsertCheckState(CheckState(auditId, categoryIndex, checkIndex, checked))
        }
    }

    suspend fun getFinding(id: Long): Finding? = dao.getFinding(id)

    fun saveFinding(finding: Finding, onDone: () -> Unit = {}) {
        viewModelScope.launch {
            if (finding.id == 0L) dao.insertFinding(finding) else dao.updateFinding(finding)
            onDone()
        }
    }

    fun deleteFinding(finding: Finding, onDone: () -> Unit = {}) {
        viewModelScope.launch {
            dao.deleteFinding(finding)
            onDone()
        }
    }
}
