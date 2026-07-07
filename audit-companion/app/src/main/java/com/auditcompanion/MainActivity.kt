package com.auditcompanion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.auditcompanion.ui.AuditListScreen
import com.auditcompanion.ui.FindingScreen
import com.auditcompanion.ui.ReportScreen
import com.auditcompanion.ui.WorkspaceScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AuditCompanionTheme {
                Surface(color = MaterialTheme.colorScheme.background) {
                    AppNavHost()
                }
            }
        }
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
                onAddFinding = { categoryIndex ->
                    navController.navigate("finding/$auditId/$categoryIndex?findingId=-1")
                },
                onEditFinding = { finding ->
                    navController.navigate(
                        "finding/$auditId/${finding.categoryIndex}?findingId=${finding.id}"
                    )
                },
                onOpenReport = { navController.navigate("report/$auditId") },
            )
        }
        composable(
            route = "finding/{auditId}/{categoryIndex}?findingId={findingId}",
            arguments = listOf(
                navArgument("auditId") { type = NavType.LongType },
                navArgument("categoryIndex") { type = NavType.IntType },
                navArgument("findingId") { type = NavType.LongType; defaultValue = -1L },
            ),
        ) { entry ->
            val args = entry.arguments!!
            FindingScreen(
                viewModel = viewModel,
                auditId = args.getLong("auditId"),
                categoryIndex = args.getInt("categoryIndex"),
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
    }
}
