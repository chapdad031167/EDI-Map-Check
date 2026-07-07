package com.chapman.wishweek.journal

import android.content.ContentValues
import android.content.Context
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import com.chapman.wishweek.data.TripContent
import java.io.File
import java.io.OutputStream

/**
 * Renders the week's journal into a one-page-per-day PDF scrapbook and saves
 * it to Downloads (via MediaStore on Android 10+, app-external Downloads on
 * older phones). Local file write only; nothing leaves the device.
 */
object PdfExporter {

    private const val PAGE_W = 595
    private const val PAGE_H = 842
    private const val MARGIN = 40f

    /** Returns a human-readable location of the saved file, or null on failure. */
    fun export(context: Context, content: TripContent, entries: List<JournalEntry>): String? {
        val byDate = entries.filter { it.text.isNotBlank() || it.photoPath != null }
            .groupBy { it.date }
            .toSortedMap()
        if (byDate.isEmpty()) return null

        val pdf = PdfDocument()
        var pageNo = 1
        for ((date, dayEntries) in byDate) {
            val page = pdf.startPage(
                PdfDocument.PageInfo.Builder(PAGE_W, PAGE_H, pageNo).create()
            )
            drawDayPage(page, content, date, dayEntries)
            pdf.finishPage(page)
            pageNo++
        }

        val fileName = "Ashtons_Wish_Week_Scrapbook.pdf"
        return try {
            val location = openDownloadsStream(context, fileName)
            location.second.use { pdf.writeTo(it) }
            location.first
        } catch (e: Exception) {
            null
        } finally {
            pdf.close()
        }
    }

    private fun openDownloadsStream(context: Context, fileName: String): Pair<String, OutputStream> {
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                put(MediaStore.MediaColumns.MIME_TYPE, "application/pdf")
                put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            }
            val uri = context.contentResolver.insert(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI, values
            ) ?: throw IllegalStateException("MediaStore insert failed")
            val stream = context.contentResolver.openOutputStream(uri)
                ?: throw IllegalStateException("openOutputStream failed")
            return "Downloads/$fileName" to stream
        }
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            ?: context.filesDir
        val file = File(dir, fileName)
        return file.absolutePath to file.outputStream()
    }

    private fun drawDayPage(
        page: PdfDocument.Page,
        content: TripContent,
        date: String,
        entries: List<JournalEntry>
    ) {
        val canvas = page.canvas
        var y = MARGIN + 10f

        val dayIndex = content.days.indexOfFirst { it.date == date }
        val day = content.days.getOrNull(dayIndex)
        val title = if (day != null) "Day ${dayIndex + 1}: ${day.title}" else date

        val titlePaint = TextPaint().apply {
            color = Color.rgb(13, 71, 161)
            textSize = 22f
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            isAntiAlias = true
        }
        val metaPaint = TextPaint().apply {
            color = Color.DKGRAY
            textSize = 12f
            isAntiAlias = true
        }
        val namePaint = TextPaint().apply {
            color = Color.BLACK
            textSize = 14f
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            isAntiAlias = true
        }
        val bodyPaint = TextPaint().apply {
            color = Color.BLACK
            textSize = 14f
            isAntiAlias = true
        }

        y = drawWrapped(canvas, title, titlePaint, y)
        y = drawWrapped(canvas, "$date  •  \"${promptForExport(content, date)}\"", metaPaint, y) + 8f

        for (entry in entries.sortedBy { it.person }) {
            if (entry.text.isNotBlank()) {
                y = drawWrapped(canvas, entry.person, namePaint, y)
                y = drawWrapped(canvas, "\"${entry.text}\"", bodyPaint, y) + 6f
            }
        }

        // Photos in a 2-wide grid below the quotes
        val photos = entries.mapNotNull { it.photoPath }
            .mapNotNull { Photos.decodeScaled(it, 480) }
        if (photos.isNotEmpty()) {
            y += 8f
            val cell = ((PAGE_W - 2 * MARGIN) - 12f) / 2f
            var x = MARGIN
            var rowH = 0f
            for (bmp in photos) {
                val scale = cell / bmp.width
                val h = bmp.height * scale
                if (y + h > PAGE_H - MARGIN) break
                val dst = android.graphics.RectF(x, y, x + cell, y + h)
                canvas.drawBitmap(bmp, null, dst, null)
                rowH = maxOf(rowH, h)
                if (x > MARGIN) {
                    x = MARGIN
                    y += rowH + 12f
                    rowH = 0f
                } else {
                    x += cell + 12f
                }
            }
        }
    }

    private fun promptForExport(content: TripContent, date: String): String =
        content.journalPrompts[date] ?: content.journalPrompts["default"] ?: "Best thing today?"

    /** Draws wrapped text at y, returns the new y below it. */
    private fun drawWrapped(
        canvas: android.graphics.Canvas,
        text: String,
        paint: TextPaint,
        y: Float
    ): Float {
        val width = (PAGE_W - 2 * MARGIN).toInt()
        val layout = StaticLayout.Builder.obtain(text, 0, text.length, paint, width)
            .setAlignment(Layout.Alignment.ALIGN_NORMAL)
            .build()
        canvas.save()
        canvas.translate(MARGIN, y)
        layout.draw(canvas)
        canvas.restore()
        return y + layout.height + 4f
    }
}
