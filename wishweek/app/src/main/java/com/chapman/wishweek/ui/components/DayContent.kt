package com.chapman.wishweek.ui.components

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.chapman.wishweek.data.FamilyMember
import com.chapman.wishweek.data.TripEvent
import com.chapman.wishweek.ui.theme.WishAmberContainer
import com.chapman.wishweek.ui.theme.WishBlueLight
import com.chapman.wishweek.ui.theme.WishGreen
import com.chapman.wishweek.ui.theme.WishRed

/** Family members with a known height, i.e. the kids. */
fun kidsOf(family: List<FamilyMember>): List<FamilyMember> =
    family.filter { it.heightInches != null }

fun heightVerdict(kid: FamilyMember, min: Int?, max: Int?): String {
    val h = kid.heightInches ?: return "${kid.name} ❓"
    val ok = (min == null || h >= min) && (max == null || h <= max)
    return if (ok) "${kid.name} ✅" else "${kid.name} ❌"
}

@Composable
fun EventRow(
    event: TripEvent,
    family: List<FamilyMember>,
    placeholders: Map<String, String?>,
    overrides: Map<String, String>
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(if (event.mustDo) WishBlueLight else MaterialTheme.colorScheme.surface)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.Top
    ) {
        Column(modifier = Modifier.width(76.dp)) {
            Text(
                text = event.time ?: "",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
        }
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (event.mustDo) {
                    Icon(
                        imageVector = Icons.Filled.Star,
                        contentDescription = "Must do",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(end = 6.dp)
                    )
                }
                TokenText(
                    raw = event.title,
                    placeholders = placeholders,
                    overrides = overrides,
                    style = MaterialTheme.typography.titleSmall
                )
            }
            if (!event.location.isNullOrBlank()) {
                TokenText(
                    raw = "📍 ${event.location}",
                    placeholders = placeholders,
                    overrides = overrides,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (!event.notes.isNullOrBlank()) {
                TokenText(
                    raw = event.notes,
                    placeholders = placeholders,
                    overrides = overrides,
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            val hasHeightRule = (event.heightMin != null && event.heightMin > 0) || event.heightMax != null
            if (hasHeightRule) {
                val label = buildString {
                    append("Height ")
                    if (event.heightMin != null && event.heightMin > 0) append("${event.heightMin}\"+")
                    if (event.heightMax != null) append(" to ${event.heightMax}\"")
                }
                val verdicts = kidsOf(family).joinToString("   ") {
                    heightVerdict(it, event.heightMin, event.heightMax)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant
                    ) {
                        Text(
                            text = "$label   $verdicts",
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun PlanBSection(
    planB: String,
    placeholders: Map<String, String?>,
    overrides: Map<String, String>
) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(WishAmberContainer)
            .clickable { expanded = !expanded }
            .padding(12.dp)
            .animateContentSize()
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = "Plan B",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.tertiary
            )
            Spacer(modifier = Modifier.weight(1f))
            Text(
                text = if (expanded) "Hide" else "Show",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.tertiary
            )
        }
        if (expanded) {
            Spacer(modifier = Modifier.padding(top = 6.dp))
            TokenText(
                raw = planB,
                placeholders = placeholders,
                overrides = overrides,
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}

/** Small colored legend used on itinerary height rules. */
object VerdictColors {
    val pass = WishGreen
    val fail = WishRed
}
