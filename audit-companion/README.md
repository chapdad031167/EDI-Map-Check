# Audit Companion

A local-only Android app that manages the **AI App Health Check** process for
auditing vibe-coded web apps. It does not inspect code itself — it manages the
checklist, captures findings, and generates the client report. You run the
actual inspection separately with Claude Code and paste findings into the app.

- Kotlin + Jetpack Compose, Material 3
- Room database — everything stays on the device
- **Zero permissions**: no network, no login, no analytics, no ads
- Min Android 8.0 (API 26)

## How the app flows

1. **Audit List (home)** — one card per audit: client, app, platform
   (Lovable / Bolt / Cursor / v0 / Other), date started, and status
   (In Progress / Report Ready / Delivered). Tap **New Audit** to start one;
   **long-press a card** to delete it (with confirmation).
2. **Audit Workspace** — the five categories in fixed order: Authentication,
   Data Security, Error Handling, Performance / Scale, Monitoring /
   Observability. Each shows its plain-language meaning, its sub-checks as
   checkboxes, a **Copy prompt** button (puts that category's Claude Code
   inspection prompt on the clipboard), and **Add Finding**. Change the audit
   status from the dropdown in the top bar; the document icon opens the report.
3. **Finding entry** — title, category, severity (Critical / High / Medium /
   Low), file/line reference, a plain-English "what it means for the client"
   note, and a collapsible paste box for raw Claude Code output (stored on the
   device, never included in the client report).
4. **Report** — auto-generated from findings, sorted worst-severity first.
   Summary, fix order, "What I can fix for you", and "Next step" are editable
   (edits save automatically). Copy the whole report as Markdown, or share it
   through the Android share sheet.

## Getting the APK (easiest way — no tools needed)

Every push that touches `audit-companion/` builds the APK on GitHub's servers:

1. On GitHub, open the repo's **Actions** tab.
2. Click the newest **Build Audit Companion APK** run (green check).
3. Scroll to **Artifacts** at the bottom and download **audit-companion-apk**.
4. Unzip it — inside is `app-debug.apk`.

## Building it yourself instead

You need JDK 17+ and the Android SDK (installing
[Android Studio](https://developer.android.com/studio) is the easiest way to
get both). Then:

```bash
cd audit-companion
./gradlew assembleDebug
```

The APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

## Installing on your phone (sideloading)

1. Get `app-debug.apk` onto the phone — email it to yourself, use Google
   Drive, or plug in a USB cable and copy it over.
2. On the phone, open the file (from the Files app, or the email/Drive
   attachment).
3. Android will warn that installs from this source aren't allowed. Tap
   **Settings** on that warning and switch on **Allow from this source**.
4. Go back and tap **Install**.
5. If Play Protect asks whether to scan or warns about an unknown developer,
   choose **Install anyway** — this is your own app; it has no internet
   permission at all.

"Audit Companion" then appears in your app drawer.

## Project layout

```
audit-companion/
├── app/src/main/java/com/auditcompanion/
│   ├── MainActivity.kt          # theme + navigation graph
│   ├── AppViewModel.kt          # single ViewModel over the Room DAO
│   ├── ReportGenerator.kt       # Markdown report builder + severity sort
│   ├── data/
│   │   ├── Models.kt            # Audit, Finding, CheckState entities + enums
│   │   ├── CategoryContent.kt   # the five categories (verbatim text + prompts)
│   │   ├── AuditDao.kt          # Room DAO
│   │   └── AppDatabase.kt       # Room database singleton
│   └── ui/
│       ├── AuditListScreen.kt   # home: audit cards, new/delete
│       ├── WorkspaceScreen.kt   # five categories, checkboxes, copy-prompt
│       ├── FindingScreen.kt     # add/edit a finding
│       ├── ReportScreen.kt      # editable fields + preview + share/copy
│       └── Common.kt            # clipboard helper, date + severity display
└── app/src/main/res/            # theme, launcher icon
```
