package com.auditcompanion.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters

class EnumConverters {
    @TypeConverter fun platformToString(v: Platform): String = v.name
    @TypeConverter fun stringToPlatform(v: String): Platform = Platform.valueOf(v)
    @TypeConverter fun statusToString(v: AuditStatus): String = v.name
    @TypeConverter fun stringToStatus(v: String): AuditStatus = AuditStatus.valueOf(v)
    @TypeConverter fun severityToString(v: Severity): String = v.name
    @TypeConverter fun stringToSeverity(v: String): Severity = Severity.valueOf(v)
}

@Database(
    entities = [Audit::class, Finding::class, CheckState::class],
    version = 1,
    exportSchema = false,
)
@TypeConverters(EnumConverters::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun auditDao(): AuditDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "audit-companion.db",
                ).build().also { instance = it }
            }
    }
}
