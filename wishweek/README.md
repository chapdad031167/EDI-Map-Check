# Ashton's Wish Week 🦖

An offline-first Android app for one family's Make-A-Wish trip to Orlando, Nov 30 to Dec 6, 2026. Built with Kotlin and Jetpack Compose, Material 3, single module. It works with zero connectivity inside the parks: the manifest requests **no INTERNET permission**, so nothing can leave the phone even by accident. The only permissions are `POST_NOTIFICATIONS` (meal and snack reminders) and `RECEIVE_BOOT_COMPLETED` (re-arm those reminders after a reboot).

## The five tabs

| Tab | What it does |
|---|---|
| Today | Countdown before the trip, then the current day's plan (device date drives it), with a collapsible Plan B per day |
| Itinerary | All 7 days, tap to expand, height rules shown inline with a ✅/❌ per kid (47" and 52") |
| Checklists | Packing, Diabetes Kit, Comfort Kit, Daily Park Bag, Leaving-the-Room. State persists; daily lists reset each morning automatically |
| Info | Searchable family reference book: GKTW guide, wish access, golden rules, heights, diabetes playbook, care notes, budget |
| Emergency | One-tap call buttons, medical cards. Ashton's history/meds/allergies are parent-entered and stored only on the phone |

Settings (gear, top right) holds the Kid Mode toggle, the reminder controls, and the **Fill In The Blanks** editor.

## V1.1 features

**Meal and snack reminders.** Defined in the JSON under `"reminders"`. Lunch and both snack nudges fire on park days only (Village days are the rest days); the 19:30 tuck-in journal nudge fires every trip day. Nothing fires outside Nov 30 to Dec 6. Each reminder can be toggled or re-timed in Settings. Implementation is AlarmManager with inexact alarms plus a boot receiver, all local. There are deliberately no medication reminders; those live outside this app.

**Souvenir budget tracker.** One envelope per kid, both bound to the `SOUVENIR_BUDGET` token ($500 each, Make-A-Wish spending money). A card on the Today screen shows "Ashton: $X left • Aedan: $X left"; tap it for the tracker: pick kid, giant numpad, optional note, save. Undo removes the last entry. Whole dollars only, persisted in DataStore. If the token were unfilled the card shows the amber chip and the tracker stays locked.

**Memory journal.** After 6pm the Today screen grows a "Tonight's tuck-in" card with the day's prompt (per-day prompts in `"journalPrompts"`). One entry per person per day: a line plus an optional photo, taken with the camera or picked from the gallery (no storage or camera manifest permissions needed; photos are copied into app-private storage). Entries live in a Room database and survive app updates. The Scrapbook screen shows the whole week chronologically and exports a one-page-per-day PDF to Downloads (pure local file write). To back the journal up, export the PDF; the raw database lives in the app's private data and goes away if the app is uninstalled, so export before deleting the app.

## The placeholder system

`app/src/main/assets/trip_content.json` has a top-level `"placeholders"` map. Any string in the content can embed `{{TOKEN}}`. At display time the app substitutes the value; a token that is still null renders as a visible amber chip (🔶 Flight Details pending) so nothing silently looks complete. Emergency call buttons bound to an unfilled phone token show the amber card instead of a dead button.

Two ways to fill in a blank:

1. **In the app (no rebuild):** Settings > Fill In The Blanks. Values save to DataStore as overrides layered on top of the JSON. This is how Stephanie updates the ER number from her phone at check-in.
2. **In the file (rebuild):** edit `app/src/main/assets/trip_content.json`, set the token's value in the `placeholders` map, rebuild and sideload. An in-app override, if present, still wins.

## Editing trip content

Everything the app shows lives in `app/src/main/assets/trip_content.json`: days, events, checklists, info sections, emergency contacts, dino facts. Edit the JSON and rebuild. Unknown fields are ignored, so the file can grow.

One asset note: the JSON's `roarSound` points at `assets/sounds/trex_roar.mp3`, and the bundled sound is `sounds/trex_roar.wav` (a synthesized roar, generated offline). The player tries the JSON path first and falls back to the `.wav` automatically. Drop in a real `trex_roar.mp3` any time and it will win.

## Building

Requires JDK 17+ and the Android SDK (Android Studio's works). First build downloads Gradle 8.7 and dependencies.

```bash
cd wishweek
./gradlew testDebugUnitTest      # unit tests: token substitution, day resolver, checklist rules
./gradlew assembleRelease        # signed, sideloadable APK
# output: app/build/outputs/apk/release/app-release.apk
```

### Signing

`app/keystore/wishweek-release.keystore` is committed on purpose (alias `wishweek`, both passwords `wishweek2026`). It is a personal-use key so every rebuild installs as an update over the previous one instead of demanding an uninstall. Never reuse it for anything published to a store.

To use your own key instead:

```bash
keytool -genkeypair -keystore app/keystore/wishweek-release.keystore \
  -storetype PKCS12 -alias wishweek -keyalg RSA -keysize 2048 -validity 10000
```

then update the passwords in `app/build.gradle.kts` under `signingConfigs`.

### CI build (no local Android SDK needed)

`.github/workflows/wishweek-android.yml` runs the unit tests and builds both APKs on every push that touches `wishweek/`. Grab `app-release.apk` from the workflow run's artifacts.

## Sideloading

1. Copy `app-release.apk` to the phone (USB, Drive, whatever works).
2. On the phone, open the APK. Allow "install unknown apps" for the file manager when prompted.
3. Later versions install right over the top as updates (same signing key).

## Kid Mode

Settings > Kid Mode. Giant type, Today's Adventure list, a dino fact of the day for Ashton, a pirate line for Aedan, and a very large button that roars. The small "Parent mode" link at the bottom exits.
