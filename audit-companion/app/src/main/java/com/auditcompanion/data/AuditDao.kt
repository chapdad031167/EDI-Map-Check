package com.auditcompanion.data

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

data class AuditCount(val auditId: Long, val cnt: Int)

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

    // Categories & checks
    @Query("SELECT * FROM categories ORDER BY sortOrder ASC")
    fun observeCategories(): Flow<List<Category>>

    @Query("SELECT * FROM checks ORDER BY sortOrder ASC")
    fun observeChecks(): Flow<List<CheckItem>>

    @Insert
    suspend fun insertCategory(category: Category): Long

    @Update
    suspend fun updateCategory(category: Category)

    @Delete
    suspend fun deleteCategory(category: Category)

    @Insert
    suspend fun insertCheck(check: CheckItem): Long

    @Update
    suspend fun updateCheck(check: CheckItem)

    @Delete
    suspend fun deleteCheck(check: CheckItem)

    // Findings
    @Query("SELECT * FROM findings WHERE auditId = :auditId ORDER BY createdAt ASC")
    fun observeFindings(auditId: Long): Flow<List<Finding>>

    @Query("SELECT * FROM findings WHERE auditId = :auditId ORDER BY createdAt ASC")
    suspend fun getFindingsList(auditId: Long): List<Finding>

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

    // Progress counts for the audit list
    @Query("SELECT auditId, COUNT(*) AS cnt FROM check_states WHERE checked = 1 GROUP BY auditId")
    fun observeCheckedCounts(): Flow<List<AuditCount>>

    @Query("SELECT auditId, COUNT(*) AS cnt FROM findings GROUP BY auditId")
    fun observeFindingCounts(): Flow<List<AuditCount>>

    // Attachments
    @Query("SELECT * FROM attachments WHERE findingId = :findingId ORDER BY id ASC")
    fun observeAttachments(findingId: Long): Flow<List<Attachment>>

    @Query("SELECT * FROM attachments WHERE findingId = :findingId ORDER BY id ASC")
    suspend fun getAttachments(findingId: Long): List<Attachment>

    @Query(
        "SELECT attachments.* FROM attachments " +
            "INNER JOIN findings ON findings.id = attachments.findingId " +
            "WHERE findings.auditId = :auditId"
    )
    suspend fun getAttachmentsForAudit(auditId: Long): List<Attachment>

    @Insert
    suspend fun insertAttachment(attachment: Attachment): Long

    @Delete
    suspend fun deleteAttachment(attachment: Attachment)

    // Full-table access for backup export/import
    @Query("SELECT * FROM audits") suspend fun getAllAudits(): List<Audit>
    @Query("SELECT * FROM categories") suspend fun getAllCategories(): List<Category>
    @Query("SELECT * FROM checks") suspend fun getAllChecks(): List<CheckItem>
    @Query("SELECT * FROM findings") suspend fun getAllFindings(): List<Finding>
    @Query("SELECT * FROM check_states") suspend fun getAllCheckStates(): List<CheckState>
    @Query("SELECT * FROM attachments") suspend fun getAllAttachments(): List<Attachment>

    // Import replaces everything; deleting audits and categories cascades the rest.
    @Query("DELETE FROM audits") suspend fun deleteAllAudits()
    @Query("DELETE FROM categories") suspend fun deleteAllCategories()
}
