package com.auditcompanion.ui

import android.content.Context
import android.os.Build
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.ClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import com.auditcompanion.data.Severity
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val CARD_DATE_FORMAT = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.US)

fun formatDate(epochMillis: Long): String =
    Instant.ofEpochMilli(epochMillis).atZone(ZoneId.systemDefault()).toLocalDate()
        .format(CARD_DATE_FORMAT)

fun copyToClipboard(context: Context, clipboard: ClipboardManager, text: String, what: String) {
    clipboard.setText(AnnotatedString(text))
    // Android 13+ shows its own "copied" overlay; older versions get a toast.
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
        Toast.makeText(context, "$what copied", Toast.LENGTH_SHORT).show()
    }
}

fun severityColor(severity: Severity): Color = when (severity) {
    Severity.CRITICAL -> Color(0xFFB3261E)
    Severity.HIGH -> Color(0xFFE65100)
    Severity.MEDIUM -> Color(0xFFF9A825)
    Severity.LOW -> Color(0xFF2E7D32)
}

@Composable
fun SeverityBadge(severity: Severity) {
    Text(
        text = severity.label,
        color = Color.White,
        style = MaterialTheme.typography.labelSmall,
        modifier = Modifier
            .background(severityColor(severity), RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}
