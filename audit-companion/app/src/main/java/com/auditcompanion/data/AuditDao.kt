package com.auditcompanion.data

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface AuditDao {

    // Audits
    @Query("SELECT * FROM audits ORDER BY dateStarted DESC")
    fun observeAudits(): Flow<List<Audit>>

    @Query("SELECT * FROM audits WHERE id = :id")
    fun observeAudit(id: Long): Flow<Audit?>

    @Insert
    suspend fun insertAudit(audit: Audit): Long

    @Update
    suspend fun updateAudit(audit: Audit)

    @Delete
    suspend fun deleteAudit(audit: Audit)

    // Findings
    @Query("SELECT * FROM findings WHERE auditId = :auditId ORDER BY createdAt ASC")
    fun observeFindings(auditId: Long): Flow<List<Finding>>

    @Query("SELECT * FROM findings WHERE id = :id")
    suspend fun getFinding(id: Long): Finding?

    @Insert
    suspend fun insertFinding(finding: Finding): Long

    @Update
    suspend fun updateFinding(finding: Finding)

    @Delete
    suspend fun deleteFinding(finding: Finding)

    // Sub-check checkbox states
    @Query("SELECT * FROM check_states WHERE auditId = :auditId")
    fun observeCheckStates(auditId: Long): Flow<List<CheckState>>

    @Upsert
    suspend fun upsertCheckState(state: CheckState)
}
