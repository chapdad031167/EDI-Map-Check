# Ashton's Wish Week 🦖

An offline-first Android app for one family's Make-A-Wish trip to Orlando, Nov 30 to Dec 6, 2026. Built with Kotlin and Jetpack Compose, Material 3, single module. It works with zero connectivity inside the parks: the manifest requests **no permissions at all, including no INTERNET**, so nothing can leave the phone even by accident.

## The five tabs

| Tab | What it does |
|---|---|
| Today | Countdown before the trip, then the current day's plan (device date drives it), with a collapsible Plan B per day |
| Itinerary | All 7 days, tap to expand, height rules shown inline with a ✅/❌ per kid (47" and 52") |
| Checklists | Packing, Diabetes Kit, Comfort Kit, Daily Park Bag, Leaving-the-Room. State persists; daily lists reset each morning automatically |
| Info | Searchable family reference book: GKTW guide, wish access, golden rules, heights, diabetes playbook, care notes, budget |
| Emergency | One-tap call buttons, medical cards. Ashton's history/meds/allergies are parent-entered and stored only on the phone |

Settings (gear, top right) holds the Kid Mode toggle and the **Fill In The Blanks** editor.

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
