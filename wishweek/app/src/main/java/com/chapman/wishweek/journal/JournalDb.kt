package com.chapman.wishweek.journal

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
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

@Database(entities = [JournalEntry::class], version = 1, exportSchema = false)
abstract class JournalDb : RoomDatabase() {
    abstract fun dao(): JournalDao

    companion object {
        @Volatile
        private var instance: JournalDb? = null

        fun get(context: Context): JournalDb =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    JournalDb::class.java,
                    "wishweek_journal.db"
                ).build().also { instance = it }
            }
    }
}
