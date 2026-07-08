package com.auditcompanion.data

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

enum class Platform(val label: String) {
    LOVABLE("Lovable"),
    BOLT("Bolt"),
    CURSOR("Cursor"),
    V0("v0"),
    OTHER("Other"),
}

enum class AuditStatus(val label: String) {
    IN_PROGRESS("In Progress"),
    REPORT_READY("Report Ready"),
    DELIVERED("Delivered"),
}

enum class Severity(val label: String) {
    CRITICAL("Critical"),
    HIGH("High"),
    MEDIUM("Medium"),
    LOW("Low"),
}

const val DEFAULT_WHAT_I_CAN_FIX =
    "Reply and I'll quote the fixes you want, flat-price, no obligation."
const val DEFAULT_NEXT_STEP =
    "Reply and tell me which fixes you'd like. I'll send a short scope and get started."

@Entity(tableName = "audits")
data class Audit(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val clientName: String,
    val appName: String,
    val platform: Platform,
    val dateStarted: Long,
    val status: AuditStatus = AuditStatus.IN_PROGRESS,
    // Report fields, editable on the Report screen.
    val preparedBy: String = "",
    val summary: String = "",
    val fixOrder: String = "", // empty = regenerate from findings
    val whatICanFix: String = DEFAULT_WHAT_I_CAN_FIX,
    val nextStep: String = DEFAULT_NEXT_STEP,
    val deliveredAt: Long? = null, // set when status first becomes Delivered
    val clientContact: String = "",
)

/** An audit category. The five built-ins are seeded; more can be added. */
@Entity(tableName = "categories")
data class Category(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val name: String,
    val meaning: String,
    val claudePrompt: String,
    val sortOrder: Int,
    val builtIn: Boolean = false,
)

/** A sub-check inside a category, shown as a checkbox in every audit. */
@Entity(
    tableName = "checks",
    foreignKeys = [
        ForeignKey(
            entity = Category::class,
            parentColumns = ["id"],
            childColumns = ["categoryId"],
            onDelete = ForeignKey.CASCADE,
        )
    ],
    indices = [Index("categoryId")],
)
data class CheckItem(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val categoryId: Long,
    val text: String,
    val sortOrder: Int,
)

@Entity(
    tableName = "findings",
    foreignKeys = [
        ForeignKey(
            entity = Audit::class,
            parentColumns = ["id"],
            childColumns = ["auditId"],
            onDelete = ForeignKey.CASCADE,
        )
    ],
    indices = [Index("auditId")],
)
data class Finding(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val auditId: Long,
    val title: String,
    // No foreign key on purpose: deleting a category keeps its findings.
    val categoryId: Long,
    val severity: Severity,
    val fileRef: String,
    val clientNote: String,
    val rawOutput: String,
    val createdAt: Long,
)

@Entity(
    tableName = "check_states",
    primaryKeys = ["auditId", "checkId"],
    foreignKeys = [
        ForeignKey(
            entity = Audit::class,
            parentColumns = ["id"],
            childColumns = ["auditId"],
            onDelete = ForeignKey.CASCADE,
        ),
        ForeignKey(
            entity = CheckItem::class,
            parentColumns = ["id"],
            childColumns = ["checkId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index("checkId")],
)
data class CheckState(
    val auditId: Long,
    val checkId: Long,
    val checked: Boolean,
)

/** A photo attached to a finding. The image file lives in app-internal storage. */
@Entity(
    tableName = "attachments",
    foreignKeys = [
        ForeignKey(
            entity = Finding::class,
            parentColumns = ["id"],
            childColumns = ["findingId"],
            onDelete = ForeignKey.CASCADE,
        )
    ],
    indices = [Index("findingId")],
)
data class Attachment(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val findingId: Long,
    val fileName: String,
)
