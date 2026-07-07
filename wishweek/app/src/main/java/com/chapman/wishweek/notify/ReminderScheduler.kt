package com.chapman.wishweek.notify

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.datastore.preferences.core.Preferences
import com.chapman.wishweek.data.PrefsStore
import com.chapman.wishweek.data.ReminderLogic
import com.chapman.wishweek.data.TripContent
import com.chapman.wishweek.data.TripRepository
import com.chapman.wishweek.data.dataStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Schedules meal/snack/journal reminders with AlarmManager. Uses inexact
 * alarms on purpose: no SCHEDULE_EXACT_ALARM permission needed and a lunch
 * nudge a minute or two late is fine. Each alarm fires ReminderReceiver,
 * which shows the notification and schedules that reminder's next occurrence.
 */
object ReminderScheduler {

    const val CHANNEL_ID = "wishweek_reminders"
    const val EXTRA_REMINDER_ID = "reminder_id"
    const val EXTRA_LABEL = "label"

    fun ensureChannel(context: Context) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Trip reminders",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Meal, snack, and tuck-in journal nudges during Wish Week"
        }
        manager.createNotificationChannel(channel)
    }

    /** Re-plan every reminder from current prefs. Safe to call repeatedly. */
    fun rescheduleAll(context: Context) {
        val content = TripRepository.load(context)
        val prefs = runBlocking { context.dataStore.data.first() }
        rescheduleAll(context, content, prefs)
    }

    fun rescheduleAll(context: Context, content: TripContent, prefs: Preferences) {
        ensureChannel(context)
        val dates = ReminderLogic.tripDates(content)
        val now = LocalDateTime.now()
        for (def in content.reminders) {
            val pending = pendingIntent(context, def.id, def.label)
            alarmManager(context).cancel(pending)
            if (!PrefsStore.reminderEnabled(prefs, def)) continue
            val time = ReminderLogic.parseTime(PrefsStore.reminderTime(prefs, def)) ?: continue
            val next = ReminderLogic.nextFire(now, def.type, time, dates) ?: continue
            scheduleAt(context, next, pending)
        }
    }

    /** Called from the receiver after showing one occurrence. */
    fun scheduleNextFor(context: Context, reminderId: String) {
        val content = TripRepository.load(context)
        val def = content.reminders.find { it.id == reminderId } ?: return
        val prefs = runBlocking { context.dataStore.data.first() }
        if (!PrefsStore.reminderEnabled(prefs, def)) return
        val time = ReminderLogic.parseTime(PrefsStore.reminderTime(prefs, def)) ?: return
        val next = ReminderLogic.nextFire(
            LocalDateTime.now(),
            def.type,
            time,
            ReminderLogic.tripDates(content)
        ) ?: return
        scheduleAt(context, next, pendingIntent(context, def.id, def.label))
    }

    private fun scheduleAt(context: Context, at: LocalDateTime, pending: PendingIntent) {
        val millis = at.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
        alarmManager(context).setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, millis, pending)
    }

    private fun alarmManager(context: Context): AlarmManager =
        context.getSystemService(Context.ALARM_SERVICE) as AlarmManager

    private fun pendingIntent(context: Context, id: String, label: String): PendingIntent {
        val intent = Intent(context, ReminderReceiver::class.java).apply {
            action = "com.chapman.wishweek.REMINDER_$id"
            putExtra(EXTRA_REMINDER_ID, id)
            putExtra(EXTRA_LABEL, label)
        }
        return PendingIntent.getBroadcast(
            context,
            id.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}
