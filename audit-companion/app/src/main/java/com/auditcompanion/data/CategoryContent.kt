package com.auditcompanion.data

data class Category(
    val name: String,
    val meaning: String,
    val checks: List<String>,
    val claudePrompt: String,
)

// The five audit categories, worked in this fixed order. Text is verbatim
// from the AI App Health Check process.
val CATEGORIES = listOf(
    Category(
        name = "Authentication",
        meaning = "Can the app actually tell who a user is, and stop imposters?",
        checks = listOf(
            "Auth checks that run only in the browser (client-side, bypassable)",
            "Sessions that don't persist",
            "Missing server-side validation of who is logged in",
            "Hard-coded credentials or tokens in the code",
        ),
        claudePrompt = "Inspect all authentication logic. Is user identity verified on the " +
            "server, or only in the browser? Can any auth check be bypassed by a modified " +
            "request? Report every file involved with line numbers and severity.",
    ),
    Category(
        name = "Data Security",
        meaning = "Can User A read or change User B's data?",
        checks = listOf(
            "Database access rules disabled or wide open (e.g. Supabase Row-Level Security off)",
            "API endpoints that return any record if you change an ID",
            "Secrets or API keys exposed in front-end code or the repo",
            "No rate limiting on expensive endpoints",
        ),
        claudePrompt = "Inspect data access controls. Can one user access another user's " +
            "records by changing a request parameter? Are database security rules enabled " +
            "and enforced? Are any API keys or secrets exposed? Report with file paths and " +
            "severity.",
    ),
    Category(
        name = "Error Handling",
        meaning = "When something unexpected happens, does the app fail gracefully or just crash?",
        checks = listOf(
            "No error boundaries",
            "Unhandled failures on network calls, timeouts, or bad input",
            "Silent failures",
        ),
        claudePrompt = "Identify where the app lacks error handling. What happens on failed " +
            "network calls, malformed input, or unexpected states? List the gaps by file " +
            "and severity.",
    ),
    Category(
        name = "Performance / Scale",
        meaning = "It works with 5 users. Does it survive 500?",
        checks = listOf(
            "Database queries inside loops (N+1 problem)",
            "No pagination on large data lists",
            "Loading everything at once instead of on demand",
        ),
        claudePrompt = "Find performance problems that would break under load: N+1 queries, " +
            "missing pagination, inefficient data fetching. Report by file with severity.",
    ),
    Category(
        name = "Monitoring / Observability",
        meaning = "If it breaks at 2 AM, does anyone find out before the customers do?",
        checks = listOf(
            "No error logging or tracking",
            "No alerts when something fails",
            "No way to see what went wrong after the fact",
        ),
        claudePrompt = "Assess observability. Is there any error logging, monitoring, or " +
            "alerting? If this app failed in production, how would the owner know? Report " +
            "gaps and severity.",
    ),
)
