package com.chapman.wishweek.ui.screens

import android.content.Context
import android.media.MediaPlayer
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.chapman.wishweek.data.DayResolver
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripPhase
import com.chapman.wishweek.ui.theme.WishBlueLight
import com.chapman.wishweek.ui.theme.WishGreen
import java.time.LocalDate

/** Play the bundled roar. Falls back from the JSON path's extension to .wav. */
fun playRoar(context: Context, assetPath: String) {
    val base = assetPath.removePrefix("assets/")
    val candidates = listOf(base, base.substringBeforeLast('.') + ".wav").distinct()
    for (path in candidates) {
        try {
            val afd = context.assets.openFd(path)
            val player = MediaPlayer()
            player.setDataSource(afd.fileDescriptor, afd.startOffset, afd.length)
            afd.close()
            player.setOnCompletionListener { it.release() }
            player.prepare()
            player.start()
            return
        } catch (_: Exception) {
            // try the next candidate
        }
    }
}

@Composable
fun KidModeScreen(
    content: TripContent,
    today: LocalDate,
    onExitKidMode: () -> Unit
) {
    val context = LocalContext.current
    val epochDay = today.toEpochDay().toInt()
    val dinoFact = content.kidMode.dinoFacts.let {
        if (it.isEmpty()) null else it[Math.floorMod(epochDay, it.size)]
    }
    val aedanLine = content.kidMode.aedanLines.let {
        if (it.isEmpty()) null else it[Math.floorMod(epochDay, it.size)]
    }
    val phase = DayResolver.resolve(today, content)

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(WishBlueLight)
            .statusBarsPadding(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            when (phase) {
                is TripPhase.BeforeTrip -> Text(
                    text = "🦖 ${phase.daysUntil} DAYS TO GO!",
                    style = MaterialTheme.typography.headlineLarge,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth()
                )
                is TripPhase.DuringTrip -> {
                    val day = content.days[phase.dayIndex]
                    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                        Text(text = day.emoji, fontSize = 64.sp)
                        Text(
                            text = "TODAY'S ADVENTURE",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Text(
                            text = day.title,
                            style = MaterialTheme.typography.headlineMedium,
                            textAlign = TextAlign.Center
                        )
                    }
                }
                is TripPhase.AfterTrip -> Text(
                    text = "⭐ WHAT A WEEK! ⭐",
                    style = MaterialTheme.typography.headlineLarge,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
        if (phase is TripPhase.DuringTrip) {
            item {
                Card {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        content.days[phase.dayIndex].events.forEach { event ->
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    text = if (event.mustDo) "⭐" else "▪️",
                                    fontSize = 22.sp,
                                    modifier = Modifier.padding(end = 10.dp)
                                )
                                Text(text = event.title, style = MaterialTheme.typography.titleMedium)
                            }
                        }
                    }
                }
            }
        }
        dinoFact?.let { fact ->
            item {
                Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFE8F5E9))) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "🦕 Ashton's dino fact of the day",
                            style = MaterialTheme.typography.titleSmall,
                            color = WishGreen
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(text = fact, style = MaterialTheme.typography.titleMedium)
                    }
                }
            }
        }
        aedanLine?.let { line ->
            item {
                Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFFFF8E1))) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "🏴‍☠️ Captain Aedan's log",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.tertiary
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(text = line, style = MaterialTheme.typography.titleMedium)
                    }
                }
            }
        }
        item {
            Button(
                onClick = { playRoar(context, content.kidMode.roarSound) },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(96.dp),
                shape = RoundedCornerShape(24.dp),
                colors = ButtonDefaults.buttonColors(containerColor = WishGreen)
            ) {
                Text(text = "🦖 PRESS FOR ROAR", fontSize = 26.sp)
            }
        }
        item {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                TextButton(onClick = onExitKidMode) {
                    Text(
                        text = "Parent mode",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}
