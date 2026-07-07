package com.chapman.wishweek.journal

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File

/** Photo files live in app-private storage: filesDir/photos/<date>_<person>.jpg */
object Photos {

    fun photoFile(context: Context, date: String, person: String): File {
        val dir = File(context.filesDir, "photos")
        if (!dir.exists()) dir.mkdirs()
        return File(dir, "${date}_${person.lowercase()}.jpg")
    }

    fun uriFor(context: Context, file: File): Uri =
        FileProvider.getUriForFile(context, context.packageName + ".fileprovider", file)

    /** Copy a picked gallery photo into app-private storage. */
    fun copyIn(context: Context, source: Uri, dest: File): Boolean = try {
        context.contentResolver.openInputStream(source)?.use { input ->
            dest.outputStream().use { output -> input.copyTo(output) }
        } != null
    } catch (_: Exception) {
        false
    }

    /** Decode a photo scaled down to roughly [maxDim] px on its longest side. */
    fun decodeScaled(path: String, maxDim: Int): Bitmap? = try {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(path, bounds)
        var sample = 1
        var longest = maxOf(bounds.outWidth, bounds.outHeight)
        while (longest / 2 >= maxDim) {
            sample *= 2
            longest /= 2
        }
        BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })
    } catch (_: Exception) {
        null
    }
}
