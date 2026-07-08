package com.auditcompanion.data

import androidx.sqlite.db.SupportSQLiteDatabase

data class SeedCategory(
    val name: String,
    val meaning: String,
    val claudePrompt: String,
    val checks: List<String>,
)

// The five built-in audit categories, in their fixed default order. Seeded
// into the database on first run and during the v1 -> v2 migration. The v1
// -> v2 migration also depends on the deterministic ids this produces
// (categories 1..5, checks numbered sequentially), so do not reorder.
val SEED_CATEGORIES = listOf(
    SeedCategory(
        name = "Authentication",
        meaning = "Can the app actually tell who a user is, and stop imposters?",
        claudePrompt = "Inspect all authentication logic. Is user identity verified on the " +
            "server, or only in the browser? Can any auth check be bypassed by a modified " +
            "request? Report every file involved with line numbers and severity.",
        checks = listOf(
            "Auth checks that run only in the browser (client-side, bypassable)",
            "Sessions that don't persist",
            "Missing server-side validation of who is logged in",
            "Hard-coded credentials or tokens in the code",
        ),
    ),
    SeedCategory(
        name = "Data Security",
        meaning = "Can User A read or change User B's data?",
        claudePrompt = "Inspect data access controls. Can one user access another user's " +
            "records by changing a request parameter? Are database security rules enabled " +
            "and enforced? Are any API keys or secrets exposed? Report with file paths and " +
            "severity.",
        checks = listOf(
            "Database access rules disabled or wide open (e.g. Supabase Row-Level Security off)",
            "API endpoints that return any record if you change an ID",
            "Secrets or API keys exposed in front-end code or the repo",
            "No rate limiting on expensive endpoints",
        ),
    ),
    SeedCategory(
        name = "Error Handling",
        meaning = "When something unexpected happens, does the app fail gracefully or just crash?",
        claudePrompt = "Identify where the app lacks error handling. What happens on failed " +
            "network calls, malformed input, or unexpected states? List the gaps by file " +
            "and severity.",
        checks = listOf(
            "No error boundaries",
            "Unhandled failures on network calls, timeouts, or bad input",
            "Silent failures",
        ),
    ),
    SeedCategory(
        name = "Performance / Scale",
        meaning = "It works with 5 users. Does it survive 500?",
        claudePrompt = "Find performance problems that would break under load: N+1 queries, " +
            "missing pagination, inefficient data fetching. Report by file with severity.",
        checks = listOf(
            "Database queries inside loops (N+1 problem)",
            "No pagination on large data lists",
            "Loading everything at once instead of on demand",
        ),
    ),
    SeedCategory(
        name = "Monitoring / Observability",
        meaning = "If it breaks at 2 AM, does anyone find out before the customers do?",
        claudePrompt = "Assess observability. Is there any error logging, monitoring, or " +
            "alerting? If this app failed in production, how would the owner know? Report " +
            "gaps and severity.",
        checks = listOf(
            "No error logging or tracking",
            "No alerts when something fails",
            "No way to see what went wrong after the fact",
        ),
    ),
)

/**
 * Inserts the built-in categories and checks with deterministic ids:
 * categories get ids 1..5, checks are numbered sequentially across
 * categories (1..17). The migration from schema v1 relies on these ids to
 * remap old (categoryIndex, checkIndex) references.
 */
fun seedDefaults(db: SupportSQLiteDatabase) {
    var categoryId = 1L
    var checkId = 1L
    SEED_CATEGORIES.forEach { cat ->
        db.execSQL(
            "INSERT INTO categories (id, name, meaning, claudePrompt, sortOrder, builtIn) " +
                "VALUES (?, ?, ?, ?, ?, 1)",
            arrayOf(categoryId, cat.name, cat.meaning, cat.claudePrompt, categoryId - 1),
        )
        cat.checks.forEachIndexed { i, text ->
            db.execSQL(
                "INSERT INTO checks (id, categoryId, text, sortOrder) VALUES (?, ?, ?, ?)",
                arrayOf(checkId, categoryId, text, i),
            )
            checkId++
        }
        categoryId++
    }
}
