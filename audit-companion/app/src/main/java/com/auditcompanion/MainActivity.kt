package com.auditcompanion

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.auditcompanion.ui.AuditListScreen
import com.auditcompanion.ui.CategoryEditScreen
import com.auditcompanion.ui.FindingScreen
import com.auditcompanion.ui.LockScreen
import com.auditcompanion.ui.ManageCategoriesScreen
import com.auditcompanion.ui.ReportScreen
import com.auditcompanion.ui.WorkspaceScreen

const val PREFS_NAME = "settings"
const val PREF_APP_LOCK = "app_lock"

class MainActivity : FragmentActivity() {

    private var unlocked by mutableStateOf(false)
    private var lockEnabled by mutableStateOf(false)

    private fun readLockPref(): Boolean =
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE).getBoolean(PREF_APP_LOCK, false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AuditCompanionTheme {
                Surface(color = MaterialTheme.colorScheme.background) {
                    if (lockEnabled && !unlocked) {
                        LockScreen(onUnlock = { authenticate() })
                    } else {
                        AppNavHost()
                    }
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        lockEnabled = readLockPref()
        if (lockEnabled && !unlocked) authenticate()
    }

    override fun onStop() {
        super.onStop()
        if (readLockPref()) unlocked = false
    }

    private fun authenticate() {
        val authenticators = BiometricManager.Authenticators.BIOMETRIC_WEAK or
            BiometricManager.Authenticators.DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(authenticators) !=
            BiometricManager.BIOMETRIC_SUCCESS
        ) {
            // No usable screen lock on the device: don't lock the user out.
            unlocked = true
            return
        }
        val prompt = BiometricPrompt(
            this,
            ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(
                    result: BiometricPrompt.AuthenticationResult,
                ) {
                    unlocked = true
                }
            },
        )
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Unlock Audit Companion")
            .setAllowedAuthenticators(authenticators)
            .build()
        prompt.authenticate(info)
    }
}

@Composable
fun AuditCompanionTheme(content: @Composable () -> Unit) {
    val colors = if (isSystemInDarkTheme()) {
        darkColorScheme(primary = Color(0xFF81C784), secondary = Color(0xFFA5D6A7))
    } else {
        lightColorScheme(primary = Color(0xFF1B5E20), secondary = Color(0xFF388E3C))
    }
    MaterialTheme(colorScheme = colors, content = content)
}

@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    val viewModel: AppViewModel = viewModel()

    NavHost(navController = navController, startDestination = "audits") {
        composable("audits") {
            AuditListScreen(
                viewModel = viewModel,
                onOpenAudit = { id -> navController.navigate("audit/$id") },
                onManageCategories = { navController.navigate("categories") },
            )
        }
        composable(
            route = "audit/{auditId}",
            arguments = listOf(navArgument("auditId") { type = NavType.LongType }),
        ) { entry ->
            val auditId = entry.arguments!!.getLong("auditId")
            WorkspaceScreen(
                viewModel = viewModel,
                auditId = auditId,
                onBack = { navController.popBackStack() },
                onAddFinding = { categoryId ->
                    navController.navigate("finding/$auditId/$categoryId?findingId=-1")
                },
                onEditFinding = { finding ->
                    navController.navigate(
                        "finding/$auditId/${finding.categoryId}?findingId=${finding.id}"
                    )
                },
                onOpenReport = { navController.navigate("report/$auditId") },
            )
        }
        composable(
            route = "finding/{auditId}/{categoryId}?findingId={findingId}",
            arguments = listOf(
                navArgument("auditId") { type = NavType.LongType },
                navArgument("categoryId") { type = NavType.LongType },
                navArgument("findingId") { type = NavType.LongType; defaultValue = -1L },
            ),
        ) { entry ->
            val args = entry.arguments!!
            FindingScreen(
                viewModel = viewModel,
                auditId = args.getLong("auditId"),
                categoryId = args.getLong("categoryId"),
                findingId = args.getLong("findingId").takeIf { it >= 0 },
                onDone = { navController.popBackStack() },
            )
        }
        composable(
            route = "report/{auditId}",
            arguments = listOf(navArgument("auditId") { type = NavType.LongType }),
        ) { entry ->
            ReportScreen(
                viewModel = viewModel,
                auditId = entry.arguments!!.getLong("auditId"),
                onBack = { navController.popBackStack() },
            )
        }
        composable("categories") {
            ManageCategoriesScreen(
                viewModel = viewModel,
                onBack = { navController.popBackStack() },
                onEditCategory = { id -> navController.navigate("category/$id") },
            )
        }
        composable(
            route = "category/{categoryId}",
            arguments = listOf(navArgument("categoryId") { type = NavType.LongType }),
        ) { entry ->
            CategoryEditScreen(
                viewModel = viewModel,
                categoryId = entry.arguments!!.getLong("categoryId"),
                onBack = { navController.popBackStack() },
            )
        }
    }
}
