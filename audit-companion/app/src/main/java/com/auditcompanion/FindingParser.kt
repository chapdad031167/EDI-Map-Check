package com.auditcompanion

import com.auditcompanion.data.Severity

data class ParsedFinding(
    val title: String?,
    val severity: Severity?,
    val fileRef: String?,
)

private val SEVERITY_REGEX =
    Regex("""\b(critical|high|medium|low)\b""", RegexOption.IGNORE_CASE)

// Candidate file references: a path-ish token with an extension, optionally
// followed by :line or :line-line.
private val FILE_REGEX =
    Regex("""[A-Za-z0-9_\-./]*[A-Za-z0-9_\-]\.[A-Za-z0-9]{1,8}(?::\d+(?:-\d+)?)?""")

// Extensions that make a bare word.ext (no slash, no line number) plausible
// as a code file rather than prose like "e.g." or a version number.
private val CODE_EXTENSIONS = setOf(
    "ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "rb", "go", "rs", "java",
    "kt", "kts", "php", "vue", "svelte", "sql", "json", "yml", "yaml", "toml",
    "env", "html", "css", "scss", "prisma", "sh", "md", "txt", "xml", "swift",
    "c", "h", "cpp", "cs", "ex", "exs", "graphql", "tf",
)

/**
 * Best-effort extraction of finding fields from raw Claude Code output.
 * Everything is optional; the user corrects afterwards.
 */
fun parseClaudeOutput(raw: String): ParsedFinding {
    val text = raw.trim()
    if (text.isEmpty()) return ParsedFinding(null, null, null)

    val severity = SEVERITY_REGEX.find(text)
        ?.groupValues?.get(1)?.uppercase()
        ?.let { name -> Severity.entries.firstOrNull { it.name == name } }

    val fileRefs = FILE_REGEX.findAll(text)
        .map { it.value.trimEnd('.') }
        .filter { candidate ->
            val hasLine = candidate.contains(':')
            val hasPath = candidate.contains('/')
            val ext = candidate.substringAfterLast('.').substringBefore(':').lowercase()
            hasLine || hasPath || ext in CODE_EXTENSIONS
        }
        .filter { it.length >= 5 }
        .distinct()
        .take(3)
        .toList()

    val title = text.lineSequence()
        .map { line ->
            line.replace("**", "")
                .replace(Regex("""^[#>\-*\d.\s\[\]]+"""), "")
                .trim()
        }
        .firstOrNull { it.length >= 4 }
        ?.let { if (it.length > 90) it.take(87) + "…" else it }

    return ParsedFinding(
        title = title,
        severity = severity,
        fileRef = fileRefs.joinToString(", ").ifBlank { null },
    )
}
