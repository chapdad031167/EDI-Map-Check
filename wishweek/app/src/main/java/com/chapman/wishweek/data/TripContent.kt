package com.chapman.wishweek.data

import kotlinx.serialization.Serializable

@Serializable
data class TripContent(
    val meta: Meta,
    val placeholders: Map<String, String?> = emptyMap(),
    val family: List<FamilyMember> = emptyList(),
    val days: List<TripDay> = emptyList(),
    val checklists: List<Checklist> = emptyList(),
    val infoSections: List<InfoSection> = emptyList(),
    val emergency: Emergency = Emergency(),
    val kidMode: KidMode = KidMode(),
    val reminders: List<ReminderDef> = emptyList(),
    val budget: BudgetConfig = BudgetConfig(),
    val journalPrompts: Map<String, String> = emptyMap()
)

@Serializable
data class Meta(
    val appName: String = "Wish Week",
    val tripStart: String,
    val tripEnd: String,
    val timezone: String = "America/New_York",
    val version: Int = 1
)

@Serializable
data class FamilyMember(
    val name: String,
    val role: String = "",
    val age: Int? = null,
    val heightInches: Int? = null,
    val notes: String? = null,
    val loves: List<String> = emptyList()
)

@Serializable
data class TripDay(
    val date: String,
    val title: String,
    val emoji: String = "",
    val park: String = "",
    val events: List<TripEvent> = emptyList(),
    val planB: String? = null
)

@Serializable
data class TripEvent(
    val time: String? = null,
    val title: String,
    val location: String? = null,
    val notes: String? = null,
    val mustDo: Boolean = false,
    val heightMin: Int? = null,
    val heightMax: Int? = null
)

@Serializable
data class Checklist(
    val id: String,
    val name: String,
    val resetDaily: Boolean = false,
    val items: List<String> = emptyList()
)

@Serializable
data class InfoSection(
    val id: String,
    val title: String,
    val blocks: List<String> = emptyList()
)

@Serializable
data class Emergency(
    val contacts: List<EmergencyContact> = emptyList(),
    val medicalCards: List<MedicalCard> = emptyList()
)

@Serializable
data class EmergencyContact(
    val label: String,
    val phoneToken: String
)

@Serializable
data class MedicalCard(
    val person: String,
    val fields: List<String> = emptyList()
)

@Serializable
data class KidMode(
    val dinoFacts: List<String> = emptyList(),
    val aedanLines: List<String> = emptyList(),
    val roarSound: String = ""
)

@Serializable
data class ReminderDef(
    val id: String,
    /** "parkDaysOnly" or "daily" */
    val type: String = "daily",
    /** 24h HH:mm */
    val time: String,
    val label: String,
    val enabledDefault: Boolean = true
)

@Serializable
data class BudgetConfig(
    val currency: String = "USD",
    val wholeDollarsOnly: Boolean = true,
    val envelopes: List<Envelope> = emptyList(),
    val preApproved: List<String> = emptyList(),
    val fundingSource: String = ""
)

@Serializable
data class Envelope(
    val kid: String,
    val startAmountToken: String
)
