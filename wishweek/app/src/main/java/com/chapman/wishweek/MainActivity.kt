package com.chapman.wishweek

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.datastore.preferences.core.emptyPreferences
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripRepository
import com.chapman.wishweek.data.dataStore
import com.chapman.wishweek.ui.screens.ChecklistsScreen
import com.chapman.wishweek.ui.screens.EmergencyScreen
import com.chapman.wishweek.ui.screens.InfoScreen
import com.chapman.wishweek.ui.screens.ItineraryScreen
import com.chapman.wishweek.ui.screens.KidModeScreen
import com.chapman.wishweek.ui.screens.SettingsScreen
import com.chapman.wishweek.ui.screens.TodayScreen
import com.chapman.wishweek.ui.theme.WishRed
import com.chapman.wishweek.ui.theme.WishWeekTheme
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDate

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

@Composable
fun WishWeekApp(content: TripContent) {
    val context = LocalContext.current
    val prefs by context.dataStore.data.collectAsState(initial = emptyPreferences())
    val overrides = PrefsStore.overridesFrom(prefs, content.placeholders.keys)
    val kidMode = prefs[PrefsStore.KID_MODE] ?: false

    // Device date drives the Today screen; refresh it once a minute so the
    // app rolls over to the next day without a restart.
    var today by remember { mutableStateOf(LocalDate.now()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(60_000)
            today = LocalDate.now()
        }
    }

    val scope = rememberCoroutineScope()

    if (kidMode) {
        KidModeScreen(content = content, today = today, onExitKidMode = {
            scope.launch { PrefsStore.setKidMode(context, false) }
        })
        return
    }

    var selectedTab by rememberSaveable { mutableIntStateOf(0) }
    var showSettings by rememberSaveable { mutableStateOf(false) }

    val pendingCount = content.placeholders.keys.count { token ->
        Tokens.resolve(token, content.placeholders, overrides) == null
    }

    BackHandler(enabled = showSettings) { showSettings = false }

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
                        text = if (showSettings) "Settings" else content.meta.appName,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.weight(1f)
                    )
                    if (!showSettings && pendingCount > 0) {
                        Text(
                            text = "🔶 $pendingCount",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(modifier = Modifier.padding(start = 4.dp))
                    }
                    IconButton(onClick = { showSettings = !showSettings }) {
                        Icon(
                            imageVector = if (showSettings) Icons.Filled.Close else Icons.Filled.Settings,
                            contentDescription = if (showSettings) "Close settings" else "Settings",
                            tint = MaterialTheme.colorScheme.onPrimary
                        )
                    }
                }
            }
        },
        bottomBar = {
            if (!showSettings) {
                NavigationBar {
                    TABS.forEachIndexed { index, tab ->
                        NavigationBarItem(
                            selected = selectedTab == index,
                            onClick = { selectedTab = index },
                            icon = {
                                Icon(
                                    imageVector = tab.icon,
                                    contentDescription = tab.label,
                                    tint = if (tab.isEmergency) WishRed
                                    else androidx.compose.ui.graphics.Color.Unspecified
                                )
                            },
                            label = {
                                Text(
                                    text = tab.label,
                                    color = if (tab.isEmergency) WishRed
                                    else androidx.compose.ui.graphics.Color.Unspecified
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
            if (showSettings) {
                SettingsScreen(
                    placeholders = content.placeholders,
                    overrides = overrides,
                    kidMode = kidMode
                )
            } else {
                when (selectedTab) {
                    0 -> TodayScreen(content = content, overrides = overrides, today = today)
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
