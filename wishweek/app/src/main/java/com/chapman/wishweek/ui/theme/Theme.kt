package com.chapman.wishweek.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.chapman.wishweek.R

// Wish Week identity: deep teal (water and calm), amber gold (the wish star),
// dino green accents. Light theme only, tuned for direct Florida sun.
val WishTeal = Color(0xFF00565C)
val WishTealLight = Color(0xFFD3EEF0)
val WishGold = Color(0xFFB97F00)
val WishGoldBright = Color(0xFFFFC53D)
val DinoGreen = Color(0xFF2E6B30)
val DinoGreenLight = Color(0xFFDCEFDA)
val InkDark = Color(0xFF1A2327)

// Legacy names still referenced across screens, remapped to the new palette.
val WishBlue = WishTeal
val WishBlueLight = WishTealLight
val WishGreen = DinoGreen
val WishAmber = Color(0xFFFFB300)
val WishAmberContainer = Color(0xFFFFF1CC)
val WishRed = Color(0xFFB3261E)
val WishRedContainer = Color(0xFFFFE5E2)

private val LightColors = lightColorScheme(
    primary = WishTeal,
    onPrimary = Color.White,
    primaryContainer = WishTealLight,
    onPrimaryContainer = InkDark,
    secondary = WishGold,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFFFEBC2),
    onSecondaryContainer = Color(0xFF4A3300),
    tertiary = DinoGreen,
    onTertiary = Color.White,
    tertiaryContainer = DinoGreenLight,
    onTertiaryContainer = InkDark,
    error = WishRed,
    onError = Color.White,
    errorContainer = WishRedContainer,
    onErrorContainer = Color(0xFF7A1B15),
    background = Color(0xFFFAF9F4),
    onBackground = InkDark,
    surface = Color.White,
    onSurface = InkDark,
    surfaceVariant = Color(0xFFEDF0EE),
    onSurfaceVariant = Color(0xFF37454A),
    outline = Color(0xFF5E6F75)
)

val Nunito = FontFamily(
    Font(R.font.nunito_regular, FontWeight.Normal),
    Font(R.font.nunito_semibold, FontWeight.SemiBold),
    Font(R.font.nunito_bold, FontWeight.Bold),
    Font(R.font.nunito_extrabold, FontWeight.ExtraBold)
)

// Real scale: display sizes for day titles, 16sp+ body, everything Nunito.
private val WishTypography = Typography(
    displayLarge = TextStyle(fontFamily = Nunito, fontSize = 52.sp, fontWeight = FontWeight.ExtraBold, lineHeight = 58.sp),
    displayMedium = TextStyle(fontFamily = Nunito, fontSize = 40.sp, fontWeight = FontWeight.ExtraBold, lineHeight = 46.sp),
    displaySmall = TextStyle(fontFamily = Nunito, fontSize = 32.sp, fontWeight = FontWeight.ExtraBold, lineHeight = 38.sp),
    headlineLarge = TextStyle(fontFamily = Nunito, fontSize = 34.sp, fontWeight = FontWeight.ExtraBold, lineHeight = 40.sp),
    headlineMedium = TextStyle(fontFamily = Nunito, fontSize = 28.sp, fontWeight = FontWeight.Bold, lineHeight = 34.sp),
    headlineSmall = TextStyle(fontFamily = Nunito, fontSize = 24.sp, fontWeight = FontWeight.Bold, lineHeight = 30.sp),
    titleLarge = TextStyle(fontFamily = Nunito, fontSize = 23.sp, fontWeight = FontWeight.Bold, lineHeight = 29.sp),
    titleMedium = TextStyle(fontFamily = Nunito, fontSize = 19.sp, fontWeight = FontWeight.Bold, lineHeight = 25.sp),
    titleSmall = TextStyle(fontFamily = Nunito, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, lineHeight = 23.sp),
    bodyLarge = TextStyle(fontFamily = Nunito, fontSize = 18.sp, lineHeight = 26.sp),
    bodyMedium = TextStyle(fontFamily = Nunito, fontSize = 16.sp, lineHeight = 23.sp),
    bodySmall = TextStyle(fontFamily = Nunito, fontSize = 14.sp, lineHeight = 20.sp),
    labelLarge = TextStyle(fontFamily = Nunito, fontSize = 16.sp, fontWeight = FontWeight.Bold, lineHeight = 22.sp),
    labelMedium = TextStyle(fontFamily = Nunito, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, lineHeight = 19.sp),
    labelSmall = TextStyle(fontFamily = Nunito, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, lineHeight = 16.sp)
)

// One spacing/radius rhythm everywhere: 16dp gaps, 16dp corners.
private val WishShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(28.dp)
)

/** Soft hero gradient per park for the Today day card. */
fun parkGradient(park: String): Brush = when {
    park.contains("Magic Kingdom", ignoreCase = true) ->
        Brush.verticalGradient(listOf(Color(0xFFE8DAF5), Color(0xFFFDEEC8)))
    park.contains("Islands", ignoreCase = true) || park.contains("Jurassic", ignoreCase = true) ->
        Brush.verticalGradient(listOf(Color(0xFFD7EFD5), Color(0xFFF3F8D8)))
    park.contains("Universal", ignoreCase = true) ->
        Brush.verticalGradient(listOf(Color(0xFFD8E7F9), Color(0xFFFDE9D2)))
    park.contains("Hollywood", ignoreCase = true) ->
        Brush.verticalGradient(listOf(Color(0xFFFBE0E6), Color(0xFFFDF3D3)))
    park.contains("Village", ignoreCase = true) ->
        Brush.verticalGradient(listOf(Color(0xFFFFE3E3), Color(0xFFFFF7D6), Color(0xFFDFF3E0), Color(0xFFDDEBF9)))
    else ->
        Brush.verticalGradient(listOf(WishTealLight, Color(0xFFFDF3D3)))
}

@Composable
fun WishWeekTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LightColors,
        typography = WishTypography,
        shapes = WishShapes,
        content = content
    )
}
