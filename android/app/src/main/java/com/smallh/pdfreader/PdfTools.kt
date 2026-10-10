package com.smallh.pdfreader

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.pdf.PdfDocument
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.provider.MediaStore
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import java.io.File
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.roundToInt

/** 首页的文件转换工作。调用方应在后台线程运行这些方法。 */
object PdfTools {
    /** 渲染 PDF 到 [outDir] 下的 PNG 文件，按页码命名并返回文件列表。 */
    fun pdfToImages(context: Context, source: Uri, outDir: File): List<File> =
        withRenderer(context, source) { renderer ->
            require(renderer.pageCount > 0) { "PDF 没有页面" }
            outDir.mkdirs()
            val files = ArrayList<File>(renderer.pageCount)
            repeat(renderer.pageCount) { index ->
                val bitmap = render(renderer, index)
                try {
                    val file = File(outDir, "page-%03d.png".format(index + 1))
                    file.outputStream().use { stream ->
                        check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)) {
                            "${file.name} 写入失败"
                        }
                    }
                    files += file
                } finally {
                    bitmap.recycle()
                }
            }
            files
        }

    /** 将 PNG 文件写入系统相册，Android 10 及以上无需存储权限。 */
    fun saveImagesToGallery(context: Context, files: List<File>): Int {
        val resolver = context.contentResolver
        val collection = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        } else {
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        }
        var saved = 0
        files.forEach { file ->
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, file.name)
                put(MediaStore.Images.Media.MIME_TYPE, "image/png")
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    put(MediaStore.Images.Media.RELATIVE_PATH,
                        "${Environment.DIRECTORY_PICTURES}/PDF转换工具")
                    put(MediaStore.Images.Media.IS_PENDING, 1)
                }
            }
            val uri = resolver.insert(collection, values)
                ?: error("无法创建相册条目 ${file.name}")
            resolver.openOutputStream(uri, "wt")?.use { stream ->
                file.inputStream().use { it.copyTo(stream) }
            } ?: error("无法写入相册 ${file.name}")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                values.clear()
                values.put(MediaStore.Images.Media.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
            }
            saved++
        }
        return saved
    }

    /** 将 PNG 文件复制到用户选择的文件夹。 */
    fun saveImagesToTree(context: Context, files: List<File>, tree: Uri): Int {
        val folder = DocumentsContract.buildDocumentUriUsingTree(
            tree, DocumentsContract.getTreeDocumentId(tree))
        files.forEach { file ->
            val output = DocumentsContract.createDocument(
                context.contentResolver, folder, "image/png", file.name)
                ?: error("无法在所选文件夹创建 ${file.name}")
            context.contentResolver.openOutputStream(output, "wt")?.use { stream ->
                file.inputStream().use { it.copyTo(stream) }
            } ?: error("无法写入 ${file.name}")
        }
        return files.size
    }

    fun imagesToPdf(context: Context, sources: List<Uri>, output: File) {
        val document = PdfDocument()
        try {
            var count = 0
            sources.forEach { uri ->
                val bitmap = decodeImage(context, uri) ?: return@forEach
                try {
                    val info = PdfDocument.PageInfo.Builder(595, 842, count + 1).create()
                    val page = document.startPage(info)
                    page.canvas.drawColor(Color.WHITE)
                    val area = RectF(24f, 24f, 571f, 818f)
                    val scale = min(area.width() / bitmap.width, area.height() / bitmap.height)
                    val width = bitmap.width * scale
                    val height = bitmap.height * scale
                    val left = area.centerX() - width / 2
                    val top = area.centerY() - height / 2
                    page.canvas.drawBitmap(bitmap, null, RectF(left, top, left + width, top + height),
                        Paint(Paint.FILTER_BITMAP_FLAG))
                    document.finishPage(page)
                    count++
                } finally {
                    bitmap.recycle()
                }
            }
            require(count > 0) { "未找到可读取的图片" }
            output.outputStream().use(document::writeTo)
        } finally {
            document.close()
        }
    }

    fun ocrPdf(context: Context, source: Uri, output: File) {
        val recognizer = TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
        val document = PdfDocument()
        try {
            var lineCount = 0
            withRenderer(context, source) { renderer ->
                require(renderer.pageCount > 0) { "PDF 没有可识别的页面" }
                repeat(renderer.pageCount) { index ->
                    val bitmap = render(renderer, index)
                    try {
                        val result = Tasks.await(
                            recognizer.process(InputImage.fromBitmap(bitmap, 0)), 90, TimeUnit.SECONDS)
                        val sourcePage = renderer.openPage(index)
                        val pageWidth = sourcePage.width
                        val pageHeight = sourcePage.height
                        sourcePage.close()
                        val page = document.startPage(
                            PdfDocument.PageInfo.Builder(pageWidth, pageHeight, index + 1).create())
                        val canvas = page.canvas
                        canvas.drawColor(Color.WHITE)
                        canvas.drawBitmap(bitmap, null,
                            RectF(0f, 0f, pageWidth.toFloat(), pageHeight.toFloat()),
                            Paint(Paint.FILTER_BITMAP_FLAG))
                        val scaleX = pageWidth.toFloat() / bitmap.width
                        val scaleY = pageHeight.toFloat() / bitmap.height
                        val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                            color = Color.argb(1, 0, 0, 0)
                            style = Paint.Style.FILL
                        }
                        result.textBlocks.forEach { block ->
                            block.lines.forEach { line ->
                                val box = line.boundingBox ?: return@forEach
                                val text = line.text.trim()
                                if (text.isEmpty()) return@forEach
                                val height = box.height() * scaleY
                                textPaint.textSize = height.coerceAtLeast(4f) * 0.85f
                                val textWidth = textPaint.measureText(text)
                                if (textWidth <= 0f) return@forEach
                                canvas.save()
                                canvas.translate(box.left * scaleX, box.bottom * scaleY - height * 0.1f)
                                canvas.scale((box.width() * scaleX / textWidth).coerceAtLeast(0.1f), 1f)
                                canvas.drawText(text, 0f, 0f, textPaint)
                                canvas.restore()
                                lineCount++
                            }
                        }
                        document.finishPage(page)
                    } finally {
                        bitmap.recycle()
                    }
                }
            }
            require(lineCount > 0) { "没有识别到文字，请确认扫描页面清晰且包含文字" }
            output.outputStream().use(document::writeTo)
        } finally {
            document.close()
            recognizer.close()
        }
    }

    private fun decodeImage(context: Context, uri: Uri): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        var sample = 1
        while (bounds.outWidth / sample > 2400 || bounds.outHeight / sample > 2400) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        return context.contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, options)
        }
    }

    private fun render(renderer: PdfRenderer, index: Int): Bitmap {
        val page = renderer.openPage(index)
        try {
            val scale = min(1800f / page.width, 2400f / page.height)
            val bitmap = Bitmap.createBitmap(
                (page.width * scale).roundToInt().coerceAtLeast(1),
                (page.height * scale).roundToInt().coerceAtLeast(1), Bitmap.Config.ARGB_8888)
            bitmap.eraseColor(Color.WHITE)
            page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
            return bitmap
        } finally {
            page.close()
        }
    }

    private inline fun <T> withRenderer(context: Context, uri: Uri, block: (PdfRenderer) -> T): T {
        val source = File(context.cacheDir, "source_${System.nanoTime()}.pdf")
        try {
            context.contentResolver.openInputStream(uri)?.use { input ->
                source.outputStream().use { input.copyTo(it) }
            } ?: error("无法读取 PDF")
            val descriptor = ParcelFileDescriptor.open(source, ParcelFileDescriptor.MODE_READ_ONLY)
            return PdfRenderer(descriptor).use(block)
        } finally {
            source.delete()
        }
    }
}
