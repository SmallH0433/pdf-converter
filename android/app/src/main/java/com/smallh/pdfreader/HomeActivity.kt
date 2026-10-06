package com.smallh.pdfreader

import android.content.Intent
import android.content.res.Configuration
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.graphics.ColorUtils
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File
import java.util.concurrent.Executors

/** iOS 首页六项功能在 Android 上的入口。文件选择和导出均使用系统文档选择器。 */
class HomeActivity : AppCompatActivity() {
    private enum class Feature(val title: String, val subtitle: String, val icon: Int, val color: Int) {
        READER("PDF 阅读器", "预览、手写批注、留言、搜索和标注变换", R.drawable.ic_folder_open, 0xFF2660FF.toInt()),
        PDF_TO_IMAGES("PDF 转图片", "将 PDF 页面导出为 PNG 图片", R.drawable.ic_select_area, 0xFFFF7700.toInt()),
        EXTRACT("页码节选", "按页码范围导出新的 PDF", R.drawable.ic_select_rect, 0xFF874BDB.toInt()),
        IMAGES_TO_PDF("图片转 PDF", "选择多张图片合成为 PDF", R.drawable.ic_image, 0xFF24A344.toInt()),
        BOOKMARKS("自动书签", "识别章节标题并生成可跳转目录", R.drawable.ic_note, 0xFF5261C9.toInt()),
        OCR("PDF OCR", "识别扫描页文字并生成可搜索 PDF", R.drawable.ic_search, 0xFF008E9A.toInt()),
    }

    private val worker = Executors.newSingleThreadExecutor()
    private var pendingFeature: Feature? = null
    private var pendingPdfUri: Uri? = null
    private var pendingOutput: File? = null

    private val openPdf = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        val feature = pendingFeature
        pendingFeature = null
        if (uri != null && feature != null) onPdfChosen(feature, uri)
    }
    private val openImages = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            val output = File(cacheDir, "images_${System.currentTimeMillis()}.pdf")
            runPdfJob("正在合成图片", output, "图片合成.pdf") {
                PdfTools.imagesToPdf(this, uris, output)
            }
        }
    }
    private val chooseFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { tree ->
        val source = pendingPdfUri
        pendingPdfUri = null
        if (tree != null && source != null) {
            runJob("正在导出 PNG", {
                val count = PdfTools.pdfToImages(this, source, tree)
                "$count 张 PNG 图片已保存到所选文件夹"
            })
        }
    }
    private val createPdf = registerForActivityResult(ActivityResultContracts.CreateDocument("application/pdf")) { uri ->
        val output = pendingOutput
        pendingOutput = null
        if (uri != null && output != null) {
            runCatching {
                contentResolver.openOutputStream(uri, "wt")?.use { stream ->
                    output.inputStream().use { it.copyTo(stream) }
                } ?: error("无法写入目标文件")
            }.onSuccess { toast("已导出 PDF") }
                .onFailure { showError("导出失败", it) }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingFeature = savedInstanceState?.getString("feature")?.let { name ->
            Feature.entries.firstOrNull { it.name == name }
        }
        pendingPdfUri = savedInstanceState?.getString("source")?.let(Uri::parse)
        pendingOutput = savedInstanceState?.getString("output")?.let(::File)
        buildHome()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        pendingFeature?.let { outState.putString("feature", it.name) }
        pendingPdfUri?.let { outState.putString("source", it.toString()) }
        pendingOutput?.let { outState.putString("output", it.absolutePath) }
        super.onSaveInstanceState(outState)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        buildHome()
    }

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }

    private fun select(feature: Feature) {
        when (feature) {
            Feature.READER -> startActivity(Intent(this, MainActivity::class.java))
            Feature.IMAGES_TO_PDF -> openImages.launch(arrayOf("image/*"))
            else -> {
                pendingFeature = feature
                openPdf.launch(arrayOf("application/pdf"))
            }
        }
    }

    private fun onPdfChosen(feature: Feature, uri: Uri) {
        when (feature) {
            Feature.PDF_TO_IMAGES -> {
                pendingPdfUri = uri
                chooseFolder.launch(null)
            }
            Feature.EXTRACT, Feature.BOOKMARKS -> {
                val intent = Intent(Intent.ACTION_VIEW, uri, this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                    .putExtra(MainActivity.EXTRA_OPEN_FEATURE,
                        if (feature == Feature.EXTRACT) MainActivity.FEATURE_EXTRACT else MainActivity.FEATURE_BOOKMARKS)
                startActivity(intent)
            }
            Feature.OCR -> {
                val output = File(cacheDir, "ocr_${System.currentTimeMillis()}.pdf")
                val name = (displayName(uri) ?: "文档.pdf").substringBeforeLast('.') + "_OCR.pdf"
                runPdfJob("正在识别 PDF", output, name) { PdfTools.ocrPdf(this, uri, output) }
            }
            else -> Unit
        }
    }

    private fun runPdfJob(title: String, output: File, exportName: String, job: () -> Unit) {
        runJob(title, {
            job()
            pendingOutput = output
            null
        }) { createPdf.launch(exportName) }
    }

    private fun runJob(title: String, job: () -> String?, success: (() -> Unit)? = null) {
        val progress = ProgressBar(this)
        val dialog = AlertDialog.Builder(this).setTitle(title)
            .setMessage("文件较大时可能需要一些时间，请稍候。")
            .setView(progress).setCancelable(false).create()
        dialog.show()
        worker.execute {
            val result = runCatching(job)
            runOnUiThread {
                dialog.dismiss()
                result.onSuccess { message ->
                    if (message != null) toast(message)
                    success?.invoke()
                }.onFailure { showError("处理失败", it) }
            }
        }
    }

    private fun buildHome() {
        val root = FrameLayout(this).apply { setBackgroundColor(colorOf(R.color.hi_bg)) }
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, bars.top, 0, bars.bottom)
            insets
        }
        val scroll = ScrollView(this).apply { isFillViewport = true; clipToPadding = false }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(28), dp(22), dp(28))
        }
        val width = (resources.displayMetrics.widthPixels - dp(16)).coerceAtMost(dp(760))
        scroll.addView(content, FrameLayout.LayoutParams(width, FrameLayout.LayoutParams.WRAP_CONTENT))
        root.addView(scroll, FrameLayout.LayoutParams(-1, -1).apply { gravity = Gravity.CENTER_HORIZONTAL })
        addLabel(content, "PDF 工具箱", 15f, R.color.hi_brand_500, true, dp(4))
        addLabel(content, "PDF 转换工具", 34f, R.color.hi_text_primary, true, dp(8))
        addLabel(content, "在 Android 手机上阅读、整理和导出 PDF。", 14f,
            R.color.hi_text_secondary, false, dp(28))
        addSection(content, "阅读与转换", listOf(Feature.READER, Feature.PDF_TO_IMAGES,
            Feature.EXTRACT, Feature.IMAGES_TO_PDF))
        addSection(content, "智能与整理", listOf(Feature.BOOKMARKS, Feature.OCR))
        addLabel(content, "Android 原生版 · 支持深色模式与手写笔", 12f,
            R.color.hi_text_tertiary, false, 0).gravity = Gravity.CENTER
        setContentView(root)
    }

    private fun addSection(parent: LinearLayout, name: String, features: List<Feature>) {
        addLabel(parent, name, 18f, R.color.hi_text_primary, true, dp(12))
        features.forEach { feature ->
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(16), dp(13), dp(16), dp(13))
                background = GradientDrawable().apply {
                    setColor(colorOf(R.color.hi_surface))
                    cornerRadius = dp(20).toFloat()
                    setStroke(dp(1), colorOf(R.color.hi_divider))
                }
                elevation = dp(2).toFloat()
                isClickable = true
                isFocusable = true
                contentDescription = "${feature.title}：${feature.subtitle}"
                setOnClickListener { select(feature) }
            }
            val iconBox = FrameLayout(this).apply {
                background = GradientDrawable().apply {
                    setColor(ColorUtils.setAlphaComponent(feature.color, 26))
                    cornerRadius = dp(14).toFloat()
                }
            }
            val icon = ImageView(this).apply {
                setImageResource(feature.icon)
                imageTintList = ColorStateList.valueOf(feature.color)
                scaleType = ImageView.ScaleType.CENTER_INSIDE
            }
            iconBox.addView(icon, FrameLayout.LayoutParams(dp(26), dp(26), Gravity.CENTER))
            card.addView(iconBox, LinearLayout.LayoutParams(dp(52), dp(52)))
            val labels = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(14), 0, dp(8), 0)
            }
            addLabel(labels, feature.title, 17f, R.color.hi_text_primary, true, dp(3))
            addLabel(labels, feature.subtitle, 13f, R.color.hi_text_secondary, false, 0)
            card.addView(labels, LinearLayout.LayoutParams(0, -2, 1f))
            card.addView(ImageView(this).apply {
                setImageResource(R.drawable.ic_chevron_right)
                imageTintList = ColorStateList.valueOf(colorOf(R.color.hi_text_tertiary))
            }, LinearLayout.LayoutParams(dp(20), dp(20)))
            parent.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(12) })
        }
    }

    private fun addLabel(parent: LinearLayout, text: String, size: Float, color: Int,
                         bold: Boolean, bottom: Int): TextView {
        val view = TextView(this).apply {
            this.text = text
            textSize = size
            setTextColor(colorOf(color))
            if (bold) typeface = Typeface.DEFAULT_BOLD
        }
        parent.addView(view, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = bottom })
        return view
    }

    private fun displayName(uri: Uri): String? = runCatching {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        }
    }.getOrNull()

    private fun showError(title: String, error: Throwable) {
        AlertDialog.Builder(this).setTitle(title).setMessage(error.message ?: "未知错误")
            .setPositiveButton("确定", null).show()
    }

    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    private fun colorOf(id: Int) = ContextCompat.getColor(this, id)
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
