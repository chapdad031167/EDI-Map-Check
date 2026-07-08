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
   (Lovable / Bolt / Cursor / v0 / Other), start and delivered dates, status,
   and live progress ("8/17 checks • 3 findings"). Tap **New Audit** to start
   one (client contact is optional); **long-press a card** for Duplicate,
   Re-audit, or Delete.
2. **Audit Workspace** — the audit categories in order (the five classics are
   built in: Authentication, Data Security, Error Handling, Performance /
   Scale, Monitoring / Observability). Each shows its plain-language meaning,
   its sub-checks as checkboxes, a **Copy prompt** button (puts that
   category's Claude Code inspection prompt on the clipboard), and **Add
   Finding**. The top bar has the status dropdown, the report, and Edit
   details (client/app/platform/contact).
3. **Finding entry** — title, category, severity (Critical / High / Medium /
   Low), file/line reference, plain-English client note, photos, and a
   collapsible paste box for raw Claude Code output. **Parse into fields**
   pre-fills the title, severity, and file references from whatever you
   pasted; you just correct it.
4. **Report** — auto-generated from findings, sorted worst-severity first,
   with a severity breakdown line. Summary, fix order, "What I can fix for
   you", and "Next step" are editable (edits save automatically). Export as
   Markdown (copy or share sheet) or as a **PDF**.

## Extra features

- **Custom categories & checks** — the checklist icon on the home screen
  opens category management: rename, reorder, or delete categories (even the
  built-ins), edit their meanings and inspection prompts, and add your own
  checks as your audit process evolves.
- **Photos on findings** — attach screenshots as evidence (system photo
  picker, no permissions). Photos stay on the device and are never included
  in the client report.
- **Re-audit** — long-press an audit and choose Re-audit when a client comes
  back after fixes: you get a fresh audit with every old finding copied in as
  "Verify fixed: …".
- **Backup / restore** — home overflow menu → Export backup writes a single
  zip (all data + photos) wherever you choose; Import backup restores it,
  replacing what's on the device. Do an export before switching phones or
  reinstalling.
- **App lock** — optional fingerprint/PIN gate (home overflow menu → App
  lock). Uses your phone's existing screen lock.

## Getting the APK (easiest way — no tools needed)

Every push that touches `audit-companion/` builds the APKs on GitHub's
servers:

1. On GitHub, open the repo's **Actions** tab.
2. Click the newest **Build Audit Companion APK** run (green check).
3. Scroll to **Artifacts** and download **audit-companion-apk** (the signed
   release build — install this one). Unzip it to get `app-release.apk`.

> **Upgrading from the original debug build?** The release APK is signed with
> a different key, so Android won't install it over the old debug install.
> Export a backup first (if you have data worth keeping — the old version has
> no backup button, so this only matters going forward), uninstall the old
> app, install `app-release.apk`, then import the backup. From then on, every
> future release APK updates in place with data intact.

## Building it yourself instead

You need JDK 17+ and the Android SDK (installing
[Android Studio](https://developer.android.com/studio) is the easiest way to
get both). Then:

```bash
cd audit-companion
./gradlew assembleRelease
```

The APK lands at `app/build/outputs/apk/release/app-release.apk`.

Note: the signing keystore in `signing/` is committed deliberately — this is
a private repo and the key exists only to keep sideloaded updates installing
over each other. Don't reuse it for anything that matters.

## Installing on your phone (sideloading)

1. Get `app-release.apk` onto the phone — email it to yourself, use Google
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
│   ├── MainActivity.kt          # theme, navigation graph, app lock
│   ├── AppViewModel.kt          # single ViewModel over the Room DAO
│   ├── ReportGenerator.kt       # Markdown report + severity sort/breakdown
│   ├── PdfExporter.kt           # paginated A4 PDF of the report
│   ├── FindingParser.kt         # "Parse into fields" heuristics
│   ├── AttachmentStore.kt       # photo files in internal storage
│   ├── BackupManager.kt         # zip export/import of everything
│   ├── data/
│   │   ├── Models.kt            # entities: Audit, Category, CheckItem,
│   │   │                        #   Finding, CheckState, Attachment
│   │   ├── SeedData.kt          # the five built-in categories
│   │   ├── AuditDao.kt          # Room DAO
│   │   └── AppDatabase.kt       # Room db, v1→v2 migration, seeding
│   └── ui/
│       ├── AuditListScreen.kt   # home: cards, progress, backup, app lock
│       ├── WorkspaceScreen.kt   # categories, checkboxes, edit details
│       ├── FindingScreen.kt     # finding editor: parse, photos
│       ├── ReportScreen.kt      # editable fields + preview + MD/PDF export
│       ├── ManageCategoriesScreen.kt / CategoryEditScreen.kt
│       ├── LockScreen.kt        # app-lock gate
│       └── Common.kt            # clipboard, dates, severity badge
├── app/src/main/res/            # theme, launcher icon, FileProvider paths
└── signing/release.keystore     # personal-use release signing key
```
