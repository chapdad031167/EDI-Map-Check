package com.auditcompanion

import com.auditcompanion.data.Audit
import com.auditcompanion.data.Finding
import com.auditcompanion.data.Severity
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

private val DATE_FORMAT = DateTimeFormatter.ofPattern("MMMM d, yyyy", Locale.US)

fun todayFormatted(): String = LocalDate.now().format(DATE_FORMAT)

/** Findings sorted worst-severity first (Critical > High > Medium > Low). */
fun sortedWorstFirst(findings: List<Finding>): List<Finding> =
    findings.sortedWith(compareBy({ it.severity.ordinal }, { it.createdAt }))

/** e.g. "2 Critical, 3 High, 1 Medium" — empty string when there are no findings. */
fun severityBreakdown(findings: List<Finding>): String =
    Severity.entries
        .map { s -> s to findings.count { it.severity == s } }
        .filter { it.second > 0 }
        .joinToString(", ") { "${it.second} ${it.first.label}" }

/** Default text for the editable "Recommended fix order" field. */
fun defaultFixOrder(findings: List<Finding>): String =
    sortedWorstFirst(findings)
        .mapIndexed { i, f -> "${i + 1}. [${f.severity.label}] ${f.title}" }
        .joinToString("\n")

private fun cell(text: String): String =
    text.replace("|", "\\|").replace("\n", " ").trim()

/** Builds the client report as Markdown, following the fixed template. */
fun buildReportMarkdown(
    audit: Audit,
    findings: List<Finding>,
    categoryNames: Map<Long, String>,
): String {
    val sorted = sortedWorstFirst(findings)
    val sb = StringBuilder()

    sb.appendLine("### AI App Health Check: ${audit.appName}")
    sb.appendLine("**Prepared by:** ${audit.preparedBy.ifBlank { "[My Name]" }} | **Date:** ${todayFormatted()}")
    sb.appendLine()
    sb.appendLine("**Summary:** ${audit.summary.trim()}")
    sb.appendLine()
    val breakdown = severityBreakdown(findings)
    if (breakdown.isNotBlank()) {
        sb.appendLine("**Severity breakdown:** $breakdown")
        sb.appendLine()
    }
    sb.appendLine("**Findings, worst first:**")
    sb.appendLine()
    sb.appendLine("| # | Issue | Category | Severity | What it means for you |")
    sb.appendLine("|---|-------|----------|----------|-----------------------|")
    sorted.forEachIndexed { i, f ->
        val category = categoryNames[f.categoryId] ?: "General"
        sb.appendLine(
            "| ${i + 1} | ${cell(f.title)} | ${cell(category)} | " +
                "${f.severity.label} | ${cell(f.clientNote)} |"
        )
    }
    sb.appendLine()
    sb.appendLine("**Recommended fix order:**")
    sb.appendLine()
    sb.appendLine(audit.fixOrder.ifBlank { defaultFixOrder(findings) })
    sb.appendLine()
    sb.appendLine("**What I can fix for you:** ${audit.whatICanFix.trim()}")
    sb.appendLine()
    sb.appendLine("**Next step:** ${audit.nextStep.trim()}")

    return sb.toString()
}
