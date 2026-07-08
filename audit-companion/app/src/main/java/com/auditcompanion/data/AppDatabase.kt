package com.auditcompanion.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

class EnumConverters {
    @TypeConverter fun platformToString(v: Platform): String = v.name
    @TypeConverter fun stringToPlatform(v: String): Platform = Platform.valueOf(v)
    @TypeConverter fun statusToString(v: AuditStatus): String = v.name
    @TypeConverter fun stringToStatus(v: String): AuditStatus = AuditStatus.valueOf(v)
    @TypeConverter fun severityToString(v: Severity): String = v.name
    @TypeConverter fun stringToSeverity(v: String): Severity = Severity.valueOf(v)
}

/**
 * v1 -> v2: audits gain deliveredAt/clientContact; categories and checks move
 * from hard-coded lists into tables (seeded with the five built-ins, whose
 * deterministic ids are used to remap the old index-based references);
 * findings switch categoryIndex -> categoryId; check_states switch
 * (categoryIndex, checkIndex) -> checkId; attachments table added.
 */
private val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        // audits: add deliveredAt (nullable) and clientContact
        db.execSQL(
            "CREATE TABLE audits_new (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "clientName TEXT NOT NULL, appName TEXT NOT NULL, " +
                "platform TEXT NOT NULL, dateStarted INTEGER NOT NULL, " +
                "status TEXT NOT NULL, preparedBy TEXT NOT NULL, " +
                "summary TEXT NOT NULL, fixOrder TEXT NOT NULL, " +
                "whatICanFix TEXT NOT NULL, nextStep TEXT NOT NULL, " +
                "deliveredAt INTEGER, clientContact TEXT NOT NULL)"
        )
        db.execSQL(
            "INSERT INTO audits_new SELECT id, clientName, appName, platform, " +
                "dateStarted, status, preparedBy, summary, fixOrder, whatICanFix, " +
                "nextStep, NULL, '' FROM audits"
        )
        db.execSQL("DROP TABLE audits")
        db.execSQL("ALTER TABLE audits_new RENAME TO audits")

        // categories + checks, seeded with the built-ins (ids 1..5 / 1..17)
        db.execSQL(
            "CREATE TABLE categories (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "name TEXT NOT NULL, meaning TEXT NOT NULL, " +
                "claudePrompt TEXT NOT NULL, sortOrder INTEGER NOT NULL, " +
                "builtIn INTEGER NOT NULL)"
        )
        db.execSQL(
            "CREATE TABLE checks (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "categoryId INTEGER NOT NULL, text TEXT NOT NULL, " +
                "sortOrder INTEGER NOT NULL, " +
                "FOREIGN KEY(categoryId) REFERENCES categories(id) " +
                "ON UPDATE NO ACTION ON DELETE CASCADE)"
        )
        db.execSQL("CREATE INDEX index_checks_categoryId ON checks (categoryId)")
        seedDefaults(db)

        // findings: categoryIndex (0-based) -> categoryId (seeded ids are 1..5)
        db.execSQL(
            "CREATE TABLE findings_new (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "auditId INTEGER NOT NULL, title TEXT NOT NULL, " +
                "categoryId INTEGER NOT NULL, severity TEXT NOT NULL, " +
                "fileRef TEXT NOT NULL, clientNote TEXT NOT NULL, " +
                "rawOutput TEXT NOT NULL, createdAt INTEGER NOT NULL, " +
                "FOREIGN KEY(auditId) REFERENCES audits(id) " +
                "ON UPDATE NO ACTION ON DELETE CASCADE)"
        )
        db.execSQL(
            "INSERT INTO findings_new SELECT id, auditId, title, categoryIndex + 1, " +
                "severity, fileRef, clientNote, rawOutput, createdAt FROM findings"
        )
        db.execSQL("DROP TABLE findings")
        db.execSQL("ALTER TABLE findings_new RENAME TO findings")
        db.execSQL("CREATE INDEX index_findings_auditId ON findings (auditId)")

        // check_states: (categoryIndex, checkIndex) -> checkId. Seeded check id
        // blocks start at 1, 5, 9, 12, 15 for the five built-in categories.
        db.execSQL(
            "CREATE TABLE check_states_new (" +
                "auditId INTEGER NOT NULL, checkId INTEGER NOT NULL, " +
                "checked INTEGER NOT NULL, PRIMARY KEY(auditId, checkId), " +
                "FOREIGN KEY(auditId) REFERENCES audits(id) " +
                "ON UPDATE NO ACTION ON DELETE CASCADE, " +
                "FOREIGN KEY(checkId) REFERENCES checks(id) " +
                "ON UPDATE NO ACTION ON DELETE CASCADE)"
        )
        db.execSQL(
            "INSERT INTO check_states_new (auditId, checkId, checked) " +
                "SELECT auditId, " +
                "(CASE categoryIndex WHEN 0 THEN 1 WHEN 1 THEN 5 WHEN 2 THEN 9 " +
                "WHEN 3 THEN 12 ELSE 15 END) + checkIndex, checked FROM check_states"
        )
        db.execSQL("DROP TABLE check_states")
        db.execSQL("ALTER TABLE check_states_new RENAME TO check_states")
        db.execSQL("CREATE INDEX index_check_states_checkId ON check_states (checkId)")

        // attachments
        db.execSQL(
            "CREATE TABLE attachments (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "findingId INTEGER NOT NULL, fileName TEXT NOT NULL, " +
                "FOREIGN KEY(findingId) REFERENCES findings(id) " +
                "ON UPDATE NO ACTION ON DELETE CASCADE)"
        )
        db.execSQL("CREATE INDEX index_attachments_findingId ON attachments (findingId)")
    }
}

@Database(
    entities = [
        Audit::class,
        Category::class,
        CheckItem::class,
        Finding::class,
        CheckState::class,
        Attachment::class,
    ],
    version = 2,
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
                )
                    .addMigrations(MIGRATION_1_2)
                    .addCallback(object : Callback() {
                        override fun onCreate(db: SupportSQLiteDatabase) {
                            seedDefaults(db) // fresh installs
                        }
                    })
                    .build()
                    .also { instance = it }
            }
    }
}
