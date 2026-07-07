package com.chapman.wishweek.data

import android.content.Context
import kotlinx.serialization.json.Json

object TripRepository {

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    fun load(context: Context): TripContent =
        context.assets.open("trip_content.json").bufferedReader().use { reader ->
            json.decodeFromString(TripContent.serializer(), reader.readText())
        }
}
