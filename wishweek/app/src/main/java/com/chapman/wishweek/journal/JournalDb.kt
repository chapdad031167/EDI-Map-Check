package com.chapman.wishweek.journal

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow

/**
 * One journal entry per person per day: a line answering the day's prompt
 * and an optional photo stored in app-private files. Room keeps this data
 * across app updates; see the README for backup notes.
 */
@Entity(tableName = "journal", primaryKeys = ["date", "person"])
data class JournalEntry(
    val date: String,
    val person: String,
    val text: String = "",
    val photoPath: String? = null
)

@Dao
interface JournalDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: JournalEntry)

    @Query("SELECT * FROM journal WHERE date = :date")
    fun entriesFor(date: String): Flow<List<JournalEntry>>

    @Query("SELECT * FROM journal ORDER BY date, person")
    fun allEntries(): Flow<List<JournalEntry>>

    @Query("SELECT * FROM journal ORDER BY date, person")
    suspend fun allEntriesOnce(): List<JournalEntry>

    @Query("DELETE FROM journal WHERE date = :date AND person = :person")
    suspend fun delete(date: String, person: String)
}

/** One itinerary override per date; the JSON blob is a serialized DayEdit. */
@Entity(tableName = "day_override")
data class DayOverrideRow(
    @PrimaryKey val date: String,
    val json: String
)

@Dao
interface ItineraryDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(row: DayOverrideRow)

    @Query("SELECT * FROM day_override")
    fun overrides(): Flow<List<DayOverrideRow>>

    @Query("DELETE FROM day_override WHERE date = :date")
    suspend fun restoreDay(date: String)

    @Query("DELETE FROM day_override")
    suspend fun restoreAll()
}

private val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS `day_override` (" +
                "`date` TEXT NOT NULL, `json` TEXT NOT NULL, PRIMARY KEY(`date`))"
        )
    }
}

@Database(entities = [JournalEntry::class, DayOverrideRow::class], version = 2, exportSchema = false)
abstract class JournalDb : RoomDatabase() {
    abstract fun dao(): JournalDao
    abstract fun itineraryDao(): ItineraryDao

    companion object {
        @Volatile
        private var instance: JournalDb? = null

        fun get(context: Context): JournalDb =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    JournalDb::class.java,
                    "wishweek_journal.db"
                ).addMigrations(MIGRATION_1_2).build().also { instance = it }
            }
    }
}
