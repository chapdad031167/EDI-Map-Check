package com.auditcompanion

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import java.io.File
import java.util.UUID

/** Finding photos live in app-internal storage: filesDir/attachments/. */
object AttachmentStore {

    fun dir(context: Context): File =
        File(context.filesDir, "attachments").apply { mkdirs() }

    fun file(context: Context, fileName: String): File = File(dir(context), fileName)

    /** Copies a picked image into internal storage; returns the new file name. */
    fun import(context: Context, uri: Uri): String {
        val fileName = "att_${UUID.randomUUID()}.jpg"
        context.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Cannot open selected image" }
            file(context, fileName).outputStream().use { output ->
                input.copyTo(output)
            }
        }
        return fileName
    }

    fun delete(context: Context, fileName: String) {
        file(context, fileName).delete()
    }

    /** Decodes a bitmap downsampled to roughly [maxDim] pixels on the long edge. */
    fun loadBitmap(context: Context, fileName: String, maxDim: Int): Bitmap? {
        val f = file(context, fileName)
        if (!f.exists()) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(f.path, bounds)
        var sample = 1
        var longEdge = maxOf(bounds.outWidth, bounds.outHeight)
        while (longEdge / 2 >= maxDim) {
            sample *= 2
            longEdge /= 2
        }
        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        return BitmapFactory.decodeFile(f.path, opts)
    }
}
