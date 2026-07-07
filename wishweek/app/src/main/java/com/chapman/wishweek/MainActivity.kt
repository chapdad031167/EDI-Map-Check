package com.chapman.wishweek

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.datastore.preferences.core.emptyPreferences
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripRepository
import com.chapman.wishweek.data.dataStore
import com.chapman.wishweek.notify.ReminderScheduler
import com.chapman.wishweek.ui.screens.BudgetScreen
import com.chapman.wishweek.ui.screens.ChecklistsScreen
import com.chapman.wishweek.ui.screens.EmergencyScreen
import com.chapman.wishweek.ui.screens.InfoScreen
import com.chapman.wishweek.ui.screens.ItineraryScreen
import com.chapman.wishweek.ui.screens.JournalScreen
import com.chapman.wishweek.ui.screens.KidModeScreen
import com.chapman.wishweek.ui.screens.ScrapbookScreen
import com.chapman.wishweek.ui.screens.SettingsScreen
import com.chapman.wishweek.ui.screens.TodayScreen
import com.chapman.wishweek.ui.theme.WishRed
import com.chapman.wishweek.ui.theme.WishWeekTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.LocalTime

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content = TripRepository.load(this)
        setContent {
            WishWeekTheme {
                WishWeekApp(content)
            }
        }
    }
}

private data class Tab(val label: String, val icon: ImageVector, val isEmergency: Boolean = false)

private val TABS = listOf(
    Tab("Today", Icons.Filled.Home),
    Tab("Itinerary", Icons.Filled.DateRange),
    Tab("Checklists", Icons.Filled.CheckCircle),
    Tab("Info", Icons.Filled.Info),
    Tab("Emergency", Icons.Filled.Warning, isEmergency = true)
)

private const val OVERLAY_SETTINGS = "settings"
private const val OVERLAY_BUDGET = "budget"
private const val OVERLAY_JOURNAL = "journal"
private const val OVERLAY_SCRAPBOOK = "scrapbook"

@Composable
fun WishWeekApp(content: TripContent) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val prefs by context.dataStore.data.collectAsState(initial = emptyPreferences())
    val overrides = PrefsStore.overridesFrom(prefs, content.placeholders.keys)
    val kidMode = prefs[PrefsStore.KID_MODE] ?: false

    // Device clock drives the Today screen and the 6pm tuck-in card; refresh
    // once a minute so both roll over without a restart.
    var today by remember { mutableStateOf(LocalDate.now()) }
    var evening by remember { mutableStateOf(LocalTime.now().hour >= 18) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(60_000)
            today = LocalDate.now()
            evening = LocalTime.now().hour >= 18
        }
    }

    // Reminders: ask for notification permission on 13+ once, then plan alarms.
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33) {
            permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        withContext(Dispatchers.IO) { ReminderScheduler.rescheduleAll(context) }
    }

    if (kidMode) {
        KidModeScreen(content = content, today = today, onExitKidMode = {
            scope.launch { PrefsStore.setKidMode(context, false) }
        })
        return
    }

    var selectedTab by rememberSaveable { mutableIntStateOf(0) }
    var overlay by rememberSaveable { mutableStateOf<String?>(null) }

    val pendingCount = content.placeholders.keys.count { token ->
        Tokens.resolve(token, content.placeholders, overrides) == null
    }

    BackHandler(enabled = overlay != null) { overlay = null }

    val title = when (overlay) {
        OVERLAY_SETTINGS -> "Settings"
        OVERLAY_BUDGET -> "Souvenir Money"
        OVERLAY_JOURNAL -> "Tuck-in Journal"
        OVERLAY_SCRAPBOOK -> "Scrapbook"
        else -> content.meta.appName
    }

    Scaffold(
        topBar = {
            Surface(color = MaterialTheme.colorScheme.primary) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .statusBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.weight(1f)
                    )
                    if (overlay == null && pendingCount > 0) {
                        Text(
                            text = "🔶 $pendingCount",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(modifier = Modifier.padding(start = 4.dp))
                    }
                    IconButton(onClick = {
                        overlay = if (overlay == null) OVERLAY_SETTINGS else null
                    }) {
                        Icon(
                            imageVector = if (overlay != null) Icons.Filled.Close else Icons.Filled.Settings,
                            contentDescription = if (overlay != null) "Close" else "Settings",
                            tint = MaterialTheme.colorScheme.onPrimary
                        )
                    }
                }
            }
        },
        bottomBar = {
            if (overlay == null) {
                NavigationBar {
                    TABS.forEachIndexed { index, tab ->
                        NavigationBarItem(
                            selected = selectedTab == index,
                            onClick = { selectedTab = index },
                            icon = {
                                Icon(
                                    imageVector = tab.icon,
                                    contentDescription = tab.label,
                                    tint = if (tab.isEmergency) WishRed else Color.Unspecified
                                )
                            },
                            label = {
                                Text(
                                    text = tab.label,
                                    color = if (tab.isEmergency) WishRed else Color.Unspecified
                                )
                            }
                        )
                    }
                }
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            when (overlay) {
                OVERLAY_SETTINGS -> SettingsScreen(
                    content = content,
                    overrides = overrides,
                    kidMode = kidMode,
                    prefs = prefs
                )
                OVERLAY_BUDGET -> BudgetScreen(
                    content = content,
                    overrides = overrides,
                    prefs = prefs
                )
                OVERLAY_JOURNAL -> JournalScreen(
                    content = content,
                    date = today,
                    onOpenScrapbook = { overlay = OVERLAY_SCRAPBOOK }
                )
                OVERLAY_SCRAPBOOK -> ScrapbookScreen(content = content)
                else -> when (selectedTab) {
                    0 -> TodayScreen(
                        content = content,
                        overrides = overrides,
                        today = today,
                        evening = evening,
                        prefs = prefs,
                        onOpenBudget = { overlay = OVERLAY_BUDGET },
                        onOpenJournal = { overlay = OVERLAY_JOURNAL },
                        onOpenScrapbook = { overlay = OVERLAY_SCRAPBOOK }
                    )
                    1 -> ItineraryScreen(content = content, overrides = overrides)
                    2 -> ChecklistsScreen(
                        checklists = content.checklists,
                        prefs = prefs,
                        today = today.toString()
                    )
                    3 -> InfoScreen(
                        sections = content.infoSections,
                        placeholders = content.placeholders,
                        overrides = overrides
                    )
                    4 -> EmergencyScreen(content = content, overrides = overrides, prefs = prefs)
                }
            }
        }
    }
}
