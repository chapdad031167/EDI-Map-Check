package com.auditcompanion

import android.content.Context
import android.net.Uri
import androidx.room.withTransaction
import com.auditcompanion.data.AppDatabase
import com.auditcompanion.data.Attachment
import com.auditcompanion.data.Audit
import com.auditcompanion.data.AuditStatus
import com.auditcompanion.data.Category
import com.auditcompanion.data.CheckItem
import com.auditcompanion.data.CheckState
import com.auditcompanion.data.Finding
import com.auditcompanion.data.Platform
import com.auditcompanion.data.Severity
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

/**
 * Full backup as a zip: data.json (all tables) + attachments/ (photo files).
 * Import REPLACES everything on the device.
 */
object BackupManager {

    private const val DATA_ENTRY = "data.json"
    private const val ATTACHMENTS_PREFIX = "attachments/"
    private const val FORMAT_VERSION = 2

    suspend fun export(context: Context, db: AppDatabase, uri: Uri) {
        val dao = db.auditDao()
        val root = JSONObject().apply {
            put("version", FORMAT_VERSION)
            put("audits", JSONArray(dao.getAllAudits().map { auditToJson(it) }))
            put("categories", JSONArray(dao.getAllCategories().map { categoryToJson(it) }))
            put("checks", JSONArray(dao.getAllChecks().map { checkToJson(it) }))
            put("findings", JSONArray(dao.getAllFindings().map { findingToJson(it) }))
            put("checkStates", JSONArray(dao.getAllCheckStates().map { checkStateToJson(it) }))
            put("attachments", JSONArray(dao.getAllAttachments().map { attachmentToJson(it) }))
        }
        val attachmentFiles = dao.getAllAttachments()

        val output = context.contentResolver.openOutputStream(uri)
            ?: error("Cannot open the selected location for writing")
        ZipOutputStream(output.buffered()).use { zip ->
            zip.putNextEntry(ZipEntry(DATA_ENTRY))
            zip.write(root.toString(2).toByteArray(Charsets.UTF_8))
            zip.closeEntry()
            attachmentFiles.forEach { att ->
                val f = AttachmentStore.file(context, att.fileName)
                if (f.exists()) {
                    zip.putNextEntry(ZipEntry(ATTACHMENTS_PREFIX + att.fileName))
                    f.inputStream().use { it.copyTo(zip) }
                    zip.closeEntry()
                }
            }
        }
    }

    suspend fun import(context: Context, db: AppDatabase, uri: Uri) {
        var dataJson: String? = null
        val tempDir = File(context.cacheDir, "import_attachments").apply {
            deleteRecursively()
            mkdirs()
        }

        val input = context.contentResolver.openInputStream(uri)
            ?: error("Cannot open the selected backup file")
        ZipInputStream(input.buffered()).use { zip ->
            var entry = zip.nextEntry
            while (entry != null) {
                when {
                    entry.name == DATA_ENTRY ->
                        dataJson = zip.readBytes().toString(Charsets.UTF_8)
                    entry.name.startsWith(ATTACHMENTS_PREFIX) && !entry.isDirectory -> {
                        // Guard against path traversal in zip entry names.
                        val name = File(entry.name.removePrefix(ATTACHMENTS_PREFIX)).name
                        if (name.isNotBlank()) {
                            File(tempDir, name).outputStream().use { zip.copyTo(it) }
                        }
                    }
                }
                entry = zip.nextEntry
            }
        }

        val root = JSONObject(dataJson ?: error("Not an Audit Companion backup (no data.json)"))
        val audits = root.optJSONArray("audits").toObjects().map { auditFromJson(it) }
        val categories = root.optJSONArray("categories").toObjects().map { categoryFromJson(it) }
        val checks = root.optJSONArray("checks").toObjects().map { checkFromJson(it) }
        val findings = root.optJSONArray("findings").toObjects().map { findingFromJson(it) }
        val checkStates =
            root.optJSONArray("checkStates").toObjects().map { checkStateFromJson(it) }
        val attachments =
            root.optJSONArray("attachments").toObjects().map { attachmentFromJson(it) }

        val dao = db.auditDao()
        db.withTransaction {
            dao.deleteAllAudits()
            dao.deleteAllCategories()
            audits.forEach { dao.insertAudit(it) }
            categories.forEach { dao.insertCategory(it) }
            checks.forEach { dao.insertCheck(it) }
            findings.forEach { dao.insertFinding(it) }
            checkStates.forEach { dao.upsertCheckState(it) }
            attachments.forEach { dao.insertAttachment(it) }
        }

        // Swap in the restored photo files only after the DB import succeeded.
        AttachmentStore.dir(context).listFiles()?.forEach { it.delete() }
        tempDir.listFiles()?.forEach { f ->
            f.copyTo(AttachmentStore.file(context, f.name), overwrite = true)
        }
        tempDir.deleteRecursively()
    }

    // ---- JSON mapping ----

    private fun JSONArray?.toObjects(): List<JSONObject> {
        if (this == null) return emptyList()
        return (0 until length()).map { getJSONObject(it) }
    }

    private inline fun <reified T : Enum<T>> enumOf(name: String, fallback: T): T =
        runCatching { enumValueOf<T>(name) }.getOrDefault(fallback)

    private fun auditToJson(a: Audit) = JSONObject().apply {
        put("id", a.id); put("clientName", a.clientName); put("appName", a.appName)
        put("platform", a.platform.name); put("dateStarted", a.dateStarted)
        put("status", a.status.name); put("preparedBy", a.preparedBy)
        put("summary", a.summary); put("fixOrder", a.fixOrder)
        put("whatICanFix", a.whatICanFix); put("nextStep", a.nextStep)
        put("deliveredAt", a.deliveredAt ?: JSONObject.NULL)
        put("clientContact", a.clientContact)
    }

    private fun auditFromJson(o: JSONObject) = Audit(
        id = o.getLong("id"),
        clientName = o.optString("clientName"),
        appName = o.optString("appName"),
        platform = enumOf(o.optString("platform"), Platform.OTHER),
        dateStarted = o.optLong("dateStarted"),
        status = enumOf(o.optString("status"), AuditStatus.IN_PROGRESS),
        preparedBy = o.optString("preparedBy"),
        summary = o.optString("summary"),
        fixOrder = o.optString("fixOrder"),
        whatICanFix = o.optString("whatICanFix"),
        nextStep = o.optString("nextStep"),
        deliveredAt = if (o.isNull("deliveredAt")) null else o.optLong("deliveredAt"),
        clientContact = o.optString("clientContact"),
    )

    private fun categoryToJson(c: Category) = JSONObject().apply {
        put("id", c.id); put("name", c.name); put("meaning", c.meaning)
        put("claudePrompt", c.claudePrompt); put("sortOrder", c.sortOrder)
        put("builtIn", c.builtIn)
    }

    private fun categoryFromJson(o: JSONObject) = Category(
        id = o.getLong("id"),
        name = o.optString("name"),
        meaning = o.optString("meaning"),
        claudePrompt = o.optString("claudePrompt"),
        sortOrder = o.optInt("sortOrder"),
        builtIn = o.optBoolean("builtIn"),
    )

    private fun checkToJson(c: CheckItem) = JSONObject().apply {
        put("id", c.id); put("categoryId", c.categoryId)
        put("text", c.text); put("sortOrder", c.sortOrder)
    }

    private fun checkFromJson(o: JSONObject) = CheckItem(
        id = o.getLong("id"),
        categoryId = o.getLong("categoryId"),
        text = o.optString("text"),
        sortOrder = o.optInt("sortOrder"),
    )

    private fun findingToJson(f: Finding) = JSONObject().apply {
        put("id", f.id); put("auditId", f.auditId); put("title", f.title)
        put("categoryId", f.categoryId); put("severity", f.severity.name)
        put("fileRef", f.fileRef); put("clientNote", f.clientNote)
        put("rawOutput", f.rawOutput); put("createdAt", f.createdAt)
    }

    private fun findingFromJson(o: JSONObject) = Finding(
        id = o.getLong("id"),
        auditId = o.getLong("auditId"),
        title = o.optString("title"),
        categoryId = o.optLong("categoryId"),
        severity = enumOf(o.optString("severity"), Severity.MEDIUM),
        fileRef = o.optString("fileRef"),
        clientNote = o.optString("clientNote"),
        rawOutput = o.optString("rawOutput"),
        createdAt = o.optLong("createdAt"),
    )

    private fun checkStateToJson(s: CheckState) = JSONObject().apply {
        put("auditId", s.auditId); put("checkId", s.checkId); put("checked", s.checked)
    }

    private fun checkStateFromJson(o: JSONObject) = CheckState(
        auditId = o.getLong("auditId"),
        checkId = o.getLong("checkId"),
        checked = o.optBoolean("checked"),
    )

    private fun attachmentToJson(a: Attachment) = JSONObject().apply {
        put("id", a.id); put("findingId", a.findingId); put("fileName", a.fileName)
    }

    private fun attachmentFromJson(o: JSONObject) = Attachment(
        id = o.getLong("id"),
        findingId = o.getLong("findingId"),
        fileName = o.optString("fileName"),
    )
}
