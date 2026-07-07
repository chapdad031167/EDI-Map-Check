package com.chapman.wishweek.notify

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.chapman.wishweek.MainActivity
import com.chapman.wishweek.R

class ReminderReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra(ReminderScheduler.EXTRA_REMINDER_ID) ?: return
        val label = intent.getStringExtra(ReminderScheduler.EXTRA_LABEL) ?: "Wish Week reminder"

        ReminderScheduler.ensureChannel(context)

        val tapIntent = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = Notification.Builder(context, ReminderScheduler.CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Ashton's Wish Week")
            .setContentText(label)
            .setStyle(Notification.BigTextStyle().bigText(label))
            .setContentIntent(tapIntent)
            .setAutoCancel(true)
            .build()

        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        // POST_NOTIFICATIONS may have been declined on 13+; notify() is a
        // silent no-op in that case, which is the behavior we want.
        manager.notify(id.hashCode(), notification)

        ReminderScheduler.scheduleNextFor(context, id)
    }
}
