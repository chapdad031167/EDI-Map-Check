package com.auditcompanion

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import com.auditcompanion.data.Audit
import com.auditcompanion.data.Finding
import java.io.File

/** Renders the client report as a paginated A4 PDF in the app cache dir. */
object PdfExporter {

    private const val PAGE_W = 595 // A4 in PostScript points
    private const val PAGE_H = 842
    private const val MARGIN = 44

    fun export(
        context: Context,
        audit: Audit,
        findings: List<Finding>,
        categoryNames: Map<Long, String>,
    ): File {
        val titlePaint = paint(19f, bold = true)
        val headingPaint = paint(13f, bold = true)
        val bodyPaint = paint(11f)
        val smallPaint = paint(9.5f).apply { color = Color.rgb(100, 100, 100) }

        val doc = PdfDocument()
        var pageNumber = 1
        var page = doc.startPage(PdfDocument.PageInfo.Builder(PAGE_W, PAGE_H, pageNumber).create())
        var canvas: Canvas = page.canvas
        var y = MARGIN.toFloat()
        val contentWidth = PAGE_W - 2 * MARGIN

        fun layoutOf(text: String, p: TextPaint): StaticLayout =
            StaticLayout.Builder.obtain(text, 0, text.length, p, contentWidth)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL)
                .build()

        fun draw(text: String, p: TextPaint, spacingAfter: Float = 6f) {
            if (text.isBlank()) return
            val layout = layoutOf(text, p)
            if (y + layout.height > PAGE_H - MARGIN) {
                doc.finishPage(page)
                pageNumber++
                page = doc.startPage(
                    PdfDocument.PageInfo.Builder(PAGE_W, PAGE_H, pageNumber).create()
                )
                canvas = page.canvas
                y = MARGIN.toFloat()
            }
            canvas.save()
            canvas.translate(MARGIN.toFloat(), y)
            layout.draw(canvas)
            canvas.restore()
            y += layout.height + spacingAfter
        }

        val sorted = sortedWorstFirst(findings)

        draw("AI App Health Check: ${audit.appName}", titlePaint, 4f)
        draw(
            "Prepared by: ${audit.preparedBy.ifBlank { "[My Name]" }}   |   Date: ${todayFormatted()}",
            smallPaint,
            14f,
        )
        draw("Summary", headingPaint, 3f)
        draw(audit.summary.trim().ifBlank { "—" }, bodyPaint, 10f)

        val breakdown = severityBreakdown(findings)
        if (breakdown.isNotBlank()) {
            draw("Severity breakdown: $breakdown", bodyPaint, 10f)
        }

        draw("Findings, worst first", headingPaint, 5f)
        if (sorted.isEmpty()) {
            draw("No findings.", bodyPaint, 10f)
        } else {
            sorted.forEachIndexed { i, f ->
                draw("${i + 1}. ${f.title}   [${f.severity.label}]", paint(11f, bold = true), 1f)
                val meta = buildList {
                    add(categoryNames[f.categoryId] ?: "General")
                    if (f.fileRef.isNotBlank()) add(f.fileRef)
                }.joinToString("   •   ")
                draw(meta, smallPaint, 2f)
                draw(f.clientNote.trim().ifBlank { "—" }, bodyPaint, 9f)
            }
        }

        draw("Recommended fix order", headingPaint, 3f)
        draw(audit.fixOrder.ifBlank { defaultFixOrder(findings) }.ifBlank { "—" }, bodyPaint, 10f)
        draw("What I can fix for you", headingPaint, 3f)
        draw(audit.whatICanFix.trim().ifBlank { "—" }, bodyPaint, 10f)
        draw("Next step", headingPaint, 3f)
        draw(audit.nextStep.trim().ifBlank { "—" }, bodyPaint, 10f)

        doc.finishPage(page)

        val outDir = File(context.cacheDir, "reports").apply { mkdirs() }
        val safeName = audit.appName.replace(Regex("""[^A-Za-z0-9 _-]"""), "").trim()
            .ifBlank { "report" }.replace(' ', '-')
        val outFile = File(outDir, "AI-App-Health-Check-$safeName.pdf")
        outFile.outputStream().use { doc.writeTo(it) }
        doc.close()
        return outFile
    }

    private fun paint(size: Float, bold: Boolean = false): TextPaint =
        TextPaint().apply {
            isAntiAlias = true
            textSize = size
            color = Color.BLACK
            typeface = if (bold) Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            else Typeface.DEFAULT
        }
}
