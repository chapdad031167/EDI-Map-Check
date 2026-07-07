package com.chapman.wishweek.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.sp

// High-contrast, light-first palette so the app stays readable in direct
// Florida sun. Dark mode is intentionally not used.
val WishBlue = Color(0xFF0D47A1)
val WishBlueLight = Color(0xFFE3F0FF)
val WishGreen = Color(0xFF1B5E20)
val WishAmber = Color(0xFFFFB300)
val WishAmberContainer = Color(0xFFFFF3D6)
val WishRed = Color(0xFFB71C1C)
val WishRedContainer = Color(0xFFFFE5E2)
val InkDark = Color(0xFF17202A)

private val LightColors = lightColorScheme(
    primary = WishBlue,
    onPrimary = Color.White,
    primaryContainer = WishBlueLight,
    onPrimaryContainer = InkDark,
    secondary = WishGreen,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFDDF3DE),
    onSecondaryContainer = InkDark,
    tertiary = Color(0xFF6A4C00),
    error = WishRed,
    onError = Color.White,
    errorContainer = WishRedContainer,
    onErrorContainer = WishRed,
    background = Color(0xFFFDFDFB),
    onBackground = InkDark,
    surface = Color.White,
    onSurface = InkDark,
    surfaceVariant = Color(0xFFF0F2F5),
    onSurfaceVariant = Color(0xFF3C4650),
    outline = Color(0xFF6B7680)
)

// Everything a notch larger than stock so it reads at arm's length.
private val WishTypography = Typography(
    headlineLarge = TextStyle(fontSize = 34.sp, fontWeight = FontWeight.Bold, lineHeight = 40.sp),
    headlineMedium = TextStyle(fontSize = 28.sp, fontWeight = FontWeight.Bold, lineHeight = 34.sp),
    headlineSmall = TextStyle(fontSize = 24.sp, fontWeight = FontWeight.Bold, lineHeight = 30.sp),
    titleLarge = TextStyle(fontSize = 23.sp, fontWeight = FontWeight.Bold, lineHeight = 29.sp),
    titleMedium = TextStyle(fontSize = 19.sp, fontWeight = FontWeight.SemiBold, lineHeight = 25.sp),
    titleSmall = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.SemiBold, lineHeight = 23.sp),
    bodyLarge = TextStyle(fontSize = 18.sp, lineHeight = 26.sp),
    bodyMedium = TextStyle(fontSize = 16.sp, lineHeight = 23.sp),
    bodySmall = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelLarge = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, lineHeight = 22.sp),
    labelMedium = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.SemiBold, lineHeight = 19.sp),
    labelSmall = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, lineHeight = 16.sp)
)

@Composable
fun WishWeekTheme(content: @Composable () -> Unit) {
    // Light theme always: park readability beats dark mode for this app.
    isSystemInDarkTheme() // read and ignored on purpose
    MaterialTheme(
        colorScheme = LightColors,
        typography = WishTypography,
        content = content
    )
}
