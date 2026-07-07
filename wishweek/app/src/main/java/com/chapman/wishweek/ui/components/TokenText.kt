package com.chapman.wishweek.ui.components

import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import com.chapman.wishweek.data.Segment
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.ui.theme.WishAmberContainer

/**
 * Renders a content string with {{TOKEN}} support. Filled tokens read as
 * normal text in bold; pending tokens show as an amber "pending" chip so a
 * missing value never silently looks complete. Also handles the content
 * file's mini markdown: **bold** spans.
 */
@Composable
fun TokenText(
    raw: String,
    placeholders: Map<String, String?>,
    overrides: Map<String, String>,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    color: Color = Color.Unspecified
) {
    Text(
        text = annotate(raw, placeholders, overrides),
        modifier = modifier,
        style = style,
        color = color
    )
}

private val BOLD = Regex("\\*\\*(.+?)\\*\\*")

fun annotate(
    raw: String,
    placeholders: Map<String, String?>,
    overrides: Map<String, String>
): AnnotatedString = buildAnnotatedString {
    for (seg in Tokens.segments(raw, placeholders, overrides)) {
        when (seg) {
            is Segment.Text -> appendWithBold(seg.text)
            is Segment.Token -> {
                if (seg.value != null) {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(seg.value) }
                } else {
                    withStyle(
                        SpanStyle(
                            background = WishAmberContainer,
                            color = Color(0xFF7A4F00),
                            fontWeight = FontWeight.SemiBold
                        )
                    ) {
                        append(" 🔶 ${prettyTokenName(seg.name)} pending ")
                    }
                }
            }
        }
    }
}

private fun androidx.compose.ui.text.AnnotatedString.Builder.appendWithBold(text: String) {
    var last = 0
    for (m in BOLD.findAll(text)) {
        if (m.range.first > last) append(text.substring(last, m.range.first))
        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(m.groupValues[1]) }
        last = m.range.last + 1
    }
    if (last < text.length) append(text.substring(last))
}

fun prettyTokenName(name: String): String =
    name.split('_').joinToString(" ") { part ->
        part.lowercase().replaceFirstChar { it.uppercase() }
    }
