package com.smallh.pdfreader

import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.RectF
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import android.widget.ImageView
import android.widget.CheckBox
import android.widget.GridLayout
import android.widget.SeekBar
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.io.File
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.destination.PDPageDestination
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.destination.PDPageFitDestination
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.outline.PDDocumentOutline
import com.tom_roush.pdfbox.pdmodel.interactive.documentnavigation.outline.PDOutlineItem
import com.tom_roush.pdfbox.text.PDFTextStripper

/**
 * 安卓版 PDF 阅读器：预览、手写笔压感标注、留言便签、全文查找（文字层）。
 * 单 Activity 实现；PDF 渲染用系统 PdfRenderer，注释读写用 PdfBox。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var pageView: PageView
    private lateinit var titleText: TextView
    private lateinit var statusText: TextView
    private lateinit var pageLabel: TextView
    private lateinit var searchRow: LinearLayout
    private lateinit var searchInput: EditText
    private lateinit var searchCount: TextView
    private lateinit var colorBtn: ImageButton
    private lateinit var modeBtn: ImageButton
    private lateinit var selBar: LinearLayout
    private lateinit var selBarScroll: HorizontalScrollView
    private lateinit var selCountLabel: TextView
    private lateinit var selColorBtn: ImageButton
    private var selColorIdx = 0
    private var currentTool = Tool.PEN
    private var selectionModeRect = true

    private var session: PdfSession? = null
    private var pdfUri: Uri? = null
    private var pdfName = "未命名"
    private var dirty = false
    private var pendingExport: File? = null

    private val toolButtons = mutableMapOf<Tool, ImageButton>()
    private val colors = listOf(
        Color.rgb(229, 57, 53) to "红",
        Color.BLACK to "黑",
        Color.rgb(30, 90, 255) to "蓝",
        Color.rgb(0, 150, 60) to "绿",
    )
    private var colorIdx = 0

    private var hits: List<SearchHit> = emptyList()
    private var currentHit = -1
    @Volatile private var searchCancelled = false
    private var searchThread: Thread? = null

    private val openPdfLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            uri?.let { openPdf(it) }
        }
    private val createPdfLauncher =
        registerForActivityResult(ActivityResultContracts.CreateDocument("application/pdf")) { uri ->
            if (uri == null) {
                pendingExport = null
            } else uri.let { target ->
                val generated = pendingExport
                if (generated == null) saveAs(target) else {
                    runCatching {
                        contentResolver.openOutputStream(target, "wt")?.use { out ->
                            generated.inputStream().use { it.copyTo(out) }
                        } ?: error("无法写入")
                    }.onSuccess { toast("已导出 PDF") }
                        .onFailure { toast("导出失败：${it.message}") }
                    pendingExport = null
                }
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                confirmDiscard { finish() }
            }
        })

        // 从其他应用的「打开方式」进入
        handleViewIntent(intent)
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        handleViewIntent(intent)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        val page = if (::pageView.isInitialized) pageView.pageIndex else 0
        val searchVisible = ::searchRow.isInitialized && searchRow.visibility == View.VISIBLE
        val searchText = if (::searchInput.isInitialized) searchInput.text.toString() else ""
        val searchStatus = if (::searchCount.isInitialized) searchCount.text else ""
        super.onConfigurationChanged(newConfig)
        buildUi()
        searchInput.setText(searchText)
        searchCount.text = searchStatus
        searchRow.visibility = if (searchVisible) View.VISIBLE else View.GONE
        session?.let { activeSession ->
            pageView.session = activeSession
            pageView.penColor = colors[colorIdx].first
            pageView.post {
                pageView.showPage(page.coerceIn(0, activeSession.pageCount - 1))
                updateStatus()
                updatePageLabel()
                refreshHighlights()
            }
        }
    }

    private fun handleViewIntent(intent: android.content.Intent?) {
        if (intent?.action == android.content.Intent.ACTION_VIEW) {
            intent.data?.let { openPdf(it) }
        }
    }

    // ---- UI ----

    private fun buildUi() {
        toolButtons.clear()
        val tabletLandscape = resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE &&
            resources.configuration.smallestScreenWidthDp >= 600
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(colorOf(R.color.hi_bg))
        }
        // 避免内容被状态栏/导航条遮挡（顶部工具条会被状态栏盖住导致上半截点不到）
        androidx.core.view.ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(
                androidx.core.view.WindowInsetsCompat.Type.systemBars())
            v.setPadding(0, bars.top, 0, bars.bottom)
            insets
        }

        // ── 顶栏：白底卡片，底部分隔线 ──
        val topBar = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(colorOf(R.color.hi_surface))
        }

        // 第一行：打开 + 文件名 + 文件操作
        val documentRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(6), dp(8), dp(6))
            addView(iconBtn(R.drawable.ic_home, "返回主页", IconStyle.GHOST) {
                returnHome()
            })
            addView(iconBtn(R.drawable.ic_folder_open, "打开 PDF", IconStyle.PRIMARY) {
                openPdfLauncher.launch(arrayOf("application/pdf"))
            })
            titleText = TextView(this@MainActivity).apply {
                text = "PDF 阅读器"
                textSize = 16f
                typeface = android.graphics.Typeface.DEFAULT_BOLD
                setTextColor(colorOf(R.color.hi_text_primary))
                maxLines = 1
                ellipsize = android.text.TextUtils.TruncateAt.END
                setPadding(dp(12), 0, dp(4), 0)
                layoutParams = LinearLayout.LayoutParams(
                    0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            addView(titleText)
            addView(iconBtn(R.drawable.ic_search, "查找", IconStyle.GHOST) { toggleSearch() })
            addView(iconBtn(R.drawable.ic_note, "目录生成", IconStyle.GHOST) { showBookmarkPreview() })
            addView(iconBtn(R.drawable.ic_select_area, "PDF 节选", IconStyle.GHOST) { showExtractPreview() })
            addView(iconBtn(R.drawable.ic_save, "保存", IconStyle.GHOST) { save() })
            addView(iconBtn(R.drawable.ic_save_as, "另存为", IconStyle.GHOST) {
                createPdfLauncher.launch(pdfName.removeSuffix(".pdf") + "_标注.pdf")
            })
        }
        topBar.addView(documentRow)

        // 手机/竖屏使用横向工具条；平板横屏时同一组工具移到左侧竖栏。
        val toolStrip = adaptiveToolStrip(tabletLandscape) {
            for ((t, icon, label) in listOf(
                Triple(Tool.SELECT, R.drawable.ic_cursor, "选择"),
                Triple(Tool.PEN, R.drawable.ic_pen, "手写"),
                Triple(Tool.NOTE, R.drawable.ic_note, "留言"),
                Triple(Tool.ERASER, R.drawable.ic_eraser, "橡皮"),
                Triple(Tool.SELECT_STROKE, R.drawable.ic_select_area, "框选笔画"))) {
                val b = iconBtn(icon, label, IconStyle.CHIP) { setTool(t) }
                toolButtons[t] = b
                addView(b)
            }
            // 框选 / 圈选切换（框选工具下生效）
            modeBtn = iconBtn(
                if (selectionModeRect) R.drawable.ic_select_rect else R.drawable.ic_lasso,
                if (selectionModeRect) "选择模式：矩形" else "选择模式：套索",
                IconStyle.CHIP,
            ) {
                selectionModeRect = !selectionModeRect
                pageView.selModeRect = selectionModeRect
                modeBtn.setImageResource(
                    if (selectionModeRect) R.drawable.ic_select_rect else R.drawable.ic_lasso)
                modeBtn.contentDescription =
                    if (selectionModeRect) "选择模式：矩形" else "选择模式：套索"
                modeBtn.tooltipText = modeBtn.contentDescription
            }
            addView(modeBtn)
            colorBtn = iconBtn(R.drawable.ic_palette, "笔色", IconStyle.CHIP) { cycleColor() }
            addView(colorBtn)
            addView(iconBtn(R.drawable.ic_undo, "撤销", IconStyle.CHIP) { undo() })
        }
        topBar.addView(divider())
        if (!tabletLandscape) topBar.addView(toolStrip)
        root.addView(topBar)

        // 选中笔画操作条（有选区时显示）
        selBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(colorOf(R.color.hi_surface))
            setPadding(dp(8), dp(6), dp(8), dp(6))
            selCountLabel = TextView(this@MainActivity).apply {
                text = "已选 0 笔"
                textSize = 13f
                setTextColor(colorOf(R.color.hi_text_secondary))
                setPadding(dp(8), 0, dp(8), 0)
            }
            addView(selCountLabel)
            selColorBtn = iconBtn(R.drawable.ic_palette, "更改所选笔画颜色", IconStyle.CHIP) {
                cycleSelectionColor()
            }
            addView(selColorBtn)
            addView(iconBtn(R.drawable.ic_zoom_in, "放大所选笔画", IconStyle.CHIP) {
                pageView.scaleSelection(1.1f)
            })
            addView(iconBtn(R.drawable.ic_zoom_out, "缩小所选笔画", IconStyle.CHIP) {
                pageView.scaleSelection(1 / 1.1f)
            })
            addView(iconBtn(R.drawable.ic_rotate_left, "向左旋转", IconStyle.CHIP) {
                pageView.rotateSelection(15f)
            })
            addView(iconBtn(R.drawable.ic_rotate_right, "向右旋转", IconStyle.CHIP) {
                pageView.rotateSelection(-15f)
            })
            addView(iconBtn(R.drawable.ic_delete, "删除所选笔画", IconStyle.CHIP) {
                pageView.deleteSelection()
            })
            addView(iconBtn(R.drawable.ic_check, "完成选择", IconStyle.CHIP) {
                pageView.clearSelection()
            })
        }
        selBarScroll = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            visibility = View.GONE
            addView(selBar)
        }
        root.addView(selBarScroll)

        // 查找行（默认隐藏）
        searchRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(colorOf(R.color.hi_surface))
            setPadding(dp(12), dp(8), dp(8), dp(8))
            visibility = View.GONE
            searchInput = EditText(this@MainActivity).apply {
                hint = "输入查找内容（文字层）"
                textSize = 14f
                setTextColor(colorOf(R.color.hi_text_primary))
                setHintTextColor(colorOf(R.color.hi_text_tertiary))
                setBackgroundResource(R.drawable.hi_input_bg)
                setPadding(dp(12), 0, dp(12), 0)
                layoutParams = LinearLayout.LayoutParams(0, dp(40), 1f)
                setSingleLine()
            }
            addView(searchInput)
            addView(iconBtn(R.drawable.ic_search, "开始查找", IconStyle.TONAL) { startSearch() })
            addView(iconBtn(R.drawable.ic_arrow_up, "上一个结果", IconStyle.TONAL) { stepHit(-1) })
            addView(iconBtn(R.drawable.ic_arrow_down, "下一个结果", IconStyle.TONAL) { stepHit(1) })
            searchCount = TextView(this@MainActivity).apply {
                textSize = 13f
                setTextColor(colorOf(R.color.hi_text_secondary))
                setPadding(dp(12), 0, dp(4), 0)
            }
            addView(searchCount)
        }
        root.addView(searchRow)

        pageView = PageView(this).apply {
            onChanged = { dirty = true; updateStatus() }
            onNoteTap = { note -> editNoteDialog(note) }
            onNotePlace = { x, y -> placeNoteDialog(x, y) }
            onPageRendered = { updatePageLabel() }
            onSelectionChanged = { count ->
                selCountLabel.text = "已选 $count 笔"
                selBarScroll.visibility = if (count > 0) View.VISIBLE else View.GONE
            }
        }
        if (tabletLandscape) {
            val readerArea = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
                addView(toolStrip, LinearLayout.LayoutParams(
                    dp(56), LinearLayout.LayoutParams.MATCH_PARENT))
                addView(divider().apply {
                    layoutParams = LinearLayout.LayoutParams(
                        dp(1), LinearLayout.LayoutParams.MATCH_PARENT)
                })
                addView(pageView, LinearLayout.LayoutParams(
                    0, LinearLayout.LayoutParams.MATCH_PARENT, 1f))
            }
            root.addView(readerArea)
        } else {
            pageView.layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
            root.addView(pageView)
        }

        // ── 底栏：状态 + 翻页导航 ──
        val bottomBar = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(colorOf(R.color.hi_surface))
        }
        bottomBar.addView(divider())
        bottomBar.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(6), dp(8), dp(6))
            statusText = TextView(this@MainActivity).apply {
                text = "打开或选择 PDF 开始阅读（单指使用工具，双指拖动缩放页面）"
                textSize = 12f
                maxLines = 1
                ellipsize = android.text.TextUtils.TruncateAt.END
                setTextColor(colorOf(R.color.hi_text_tertiary))
                setPadding(dp(8), 0, dp(8), 0)
                layoutParams = LinearLayout.LayoutParams(
                    0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            addView(statusText)
            addView(iconBtn(R.drawable.ic_chevron_left, "上一页", IconStyle.TONAL) {
                showPage(pageView.pageIndex - 1)
            })
            pageLabel = TextView(this@MainActivity).apply {
                text = "0 / 0"
                textSize = 13f
                gravity = Gravity.CENTER
                setTextColor(colorOf(R.color.hi_text_primary))
                setPadding(dp(8), 0, dp(8), 0)
            }
            addView(pageLabel)
            addView(iconBtn(R.drawable.ic_chevron_right, "下一页", IconStyle.TONAL) {
                showPage(pageView.pageIndex + 1)
            })
            addView(iconBtn(R.drawable.ic_fit_width, "适应宽度", IconStyle.GHOST) {
                pageView.fitToWidth()
            })
        })
        root.addView(bottomBar)

        setContentView(root)
        updateColorBtnText()
        updateSelColorBtnText()
        pageView.penColor = colors[colorIdx].first
        pageView.selModeRect = selectionModeRect
        setTool(currentTool)
    }

    // ---- 米家 / HiUI 风格控件工厂（24dp 图标、圆角 8dp、轻量状态色） ----

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun colorOf(res: Int) = ContextCompat.getColor(this, res)

    private fun divider(): View = View(this).apply {
        setBackgroundColor(colorOf(R.color.hi_divider))
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(1))
    }

    private fun adaptiveToolStrip(
        vertical: Boolean,
        build: LinearLayout.() -> Unit,
    ): View {
        val buttons = LinearLayout(this).apply {
            orientation = if (vertical) LinearLayout.VERTICAL else LinearLayout.HORIZONTAL
            gravity = if (vertical) Gravity.CENTER_HORIZONTAL else Gravity.CENTER_VERTICAL
            setPadding(
                if (vertical) dp(4) else dp(8),
                if (vertical) dp(4) else 0,
                if (vertical) dp(4) else dp(8),
                dp(8),
            )
            build()
            for (index in 0 until childCount) {
                (getChildAt(index).layoutParams as? LinearLayout.LayoutParams)?.let { params ->
                    params.marginStart = if (vertical) 0 else dp(4)
                    params.topMargin = if (vertical && index > 0) dp(4) else 0
                }
            }
        }
        return if (vertical) {
            ScrollView(this).apply {
                isVerticalScrollBarEnabled = false
                isFillViewport = true
                setBackgroundColor(colorOf(R.color.hi_surface))
                addView(buttons, ScrollView.LayoutParams(
                    ScrollView.LayoutParams.MATCH_PARENT,
                    ScrollView.LayoutParams.WRAP_CONTENT))
            }
        } else {
            HorizontalScrollView(this).apply {
                isHorizontalScrollBarEnabled = false
                addView(buttons)
            }
        }
    }

    private enum class IconStyle { PRIMARY, TONAL, GHOST, CHIP }

    /** 米家/HiUI 风格图标按钮：24dp 图标、40dp 视觉容器、圆角与状态色统一。 */
    private fun iconBtn(
        icon: Int,
        label: String,
        style: IconStyle,
        onClick: () -> Unit,
    ): ImageButton = ImageButton(this).apply {
        setImageResource(icon)
        contentDescription = label
        tooltipText = label
        scaleType = android.widget.ImageView.ScaleType.CENTER
        setPadding(dp(8), dp(8), dp(8), dp(8))
        minimumWidth = 0
        minimumHeight = 0
        stateListAnimator = null
        setBackgroundResource(when (style) {
            IconStyle.PRIMARY -> R.drawable.hi_btn_primary
            IconStyle.TONAL -> R.drawable.hi_btn_tonal
            IconStyle.GHOST -> R.drawable.hi_btn_ghost
            IconStyle.CHIP -> R.drawable.hi_chip
        })
        imageTintList = when (style) {
            IconStyle.PRIMARY -> ColorStateList.valueOf(Color.WHITE)
            IconStyle.GHOST -> ColorStateList.valueOf(colorOf(R.color.hi_brand_500))
            IconStyle.TONAL -> ColorStateList.valueOf(colorOf(R.color.hi_text_primary))
            IconStyle.CHIP -> ContextCompat.getColorStateList(
                this@MainActivity, R.color.hi_icon_chip)
        }
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(dp(40), dp(40)).apply {
            marginStart = dp(4)
        }
    }

    // ---- 文件 ----

    private fun returnHome() {
        if (session == null) return
        if (!dirty) {
            closePdf()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("未保存的修改")
            .setMessage("返回主页前是否保存当前 PDF？")
            .setPositiveButton("保存并返回") { _, _ ->
                val s = session ?: return@setPositiveButton
                val uri = pdfUri ?: return@setPositiveButton
                try {
                    val out = File(cacheDir, "save_tmp.pdf")
                    s.saveTo(out)
                    contentResolver.openOutputStream(uri, "wt")?.use { os ->
                        out.inputStream().use { it.copyTo(os) }
                    } ?: error("无法写入原文件")
                    dirty = false
                    closePdf()
                } catch (e: Exception) {
                    AlertDialog.Builder(this)
                        .setTitle("保存失败")
                        .setMessage("${e.message}\n请先使用另存为保存副本。")
                        .setPositiveButton("确定", null)
                        .show()
                }
            }
            .setNegativeButton("放弃修改") { _, _ -> closePdf() }
            .setNeutralButton("取消", null)
            .show()
    }

    private fun closePdf() {
        searchCancelled = true
        searchThread?.interrupt()
        searchThread = null
        hits = emptyList()
        currentHit = -1
        session?.close()
        session = null
        pdfUri = null
        pdfName = "未命名"
        dirty = false
        pageView.clearSelection()
        pageView.session = null
        pageView.setHighlights(emptyList())
        pageView.invalidate()
        searchInput.text.clear()
        searchCount.text = ""
        searchRow.visibility = View.GONE
        titleText.text = "PDF 阅读器"
        statusText.text = "打开或选择 PDF 开始阅读（单指使用工具，双指拖动缩放页面）"
        pageLabel.text = "0 / 0"
    }

    private fun openPdf(uri: Uri) {
        confirmDiscard {
            android.util.Log.i("PdfReader", "openPdf: $uri")
            runCatching {
                contentResolver.takePersistableUriPermission(
                    uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or
                         android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            }
            pdfName = queryDisplayName(uri) ?: "未命名.pdf"
            val tmp = File(cacheDir, "session.pdf")
            try {
                contentResolver.openInputStream(uri).use { input ->
                    requireNotNull(input) { "无法读取文件" }
                    tmp.outputStream().use { input.copyTo(it) }
                }
                session?.close()
                session = PdfSession(this, tmp)
                pdfUri = uri
                dirty = false
                hits = emptyList()
                currentHit = -1
                pageView.session = session
                pageView.post { pageView.showPage(0) }
                updateStatus()
                updatePageLabel()
            } catch (e: Exception) {
                android.util.Log.e("PdfReader", "openPdf failed", e)
                toast("打开失败：${e.message}")
            }
        }
    }

    private data class BookmarkDraft(val title: EditText, val page: EditText)

    private fun showBookmarkPreview() {
        val active = session ?: run { toast("请先打开 PDF"); return }
        val detected = runCatching {
            synchronized(active.docLock) {
                val stripper = PDFTextStripper()
                (0 until active.pageCount).mapNotNull { page ->
                    stripper.startPage = page + 1
                    stripper.endPage = page + 1
                    stripper.getText(active.doc).lineSequence().map { it.trim() }.firstOrNull { line ->
                        line.length in 3..100 && (line.matches(Regex("^(第.{1,12}[章节篇部].*|[0-9一二三四五六七八九十]+[、.． ]+.{2,})$")) ||
                            line.matches(Regex("^[0-9]+(\\.[0-9]+){0,3}\\s+.{2,70}$")))
                    }?.let { page to it }
                }
            }
        }.getOrElse { toast("目录识别失败：${it.message}"); return }
        if (detected.isEmpty()) { toast("未识别到目录标题（扫描版请先进行 OCR）"); return }

        val drafts = mutableListOf<BookmarkDraft>()
        val rows = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        fun appendRow(title: String, page: Int) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(12), dp(4), dp(12), dp(4))
            }
            val titleInput = EditText(this).apply {
                setText(title); hint = "目录标题"; textSize = 14f; setSingleLine()
                setBackgroundResource(R.drawable.hi_input_bg)
                layoutParams = LinearLayout.LayoutParams(0, dp(46), 1f)
            }
            val pageInput = EditText(this).apply {
                setText(page.toString()); hint = "页码"; textSize = 14f
                inputType = InputType.TYPE_CLASS_NUMBER; gravity = Gravity.CENTER
                setBackgroundResource(R.drawable.hi_input_bg)
                layoutParams = LinearLayout.LayoutParams(dp(64), dp(46)).apply { marginStart = dp(8) }
            }
            val remove = TextView(this).apply {
                text = "删除"; setTextColor(colorOf(R.color.hi_brand_500)); gravity = Gravity.CENTER
                setPadding(dp(8), 0, dp(4), 0)
            }
            remove.setOnClickListener { rows.removeView(row); drafts.removeAll { it.title === titleInput } }
            row.addView(titleInput); row.addView(pageInput); row.addView(remove)
            rows.addView(row); drafts.add(BookmarkDraft(titleInput, pageInput))
        }
        detected.forEach { (page, title) -> appendRow(title, page + 1) }
        val scroller = ScrollView(this).apply { addView(rows) }
        val dialog = AlertDialog.Builder(this).setTitle("目录预览 · ${drafts.size} 项")
            .setView(scroller).setNeutralButton("添加", null).setNegativeButton("取消", null)
            .setPositiveButton("导出书签 PDF", null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener { appendRow("新目录项", 1) }
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val items = drafts.mapNotNull { draft ->
                    val title = draft.title.text.toString().trim()
                    val page = draft.page.text.toString().toIntOrNull()?.minus(1)
                    if (title.isNotEmpty() && page != null && page in 0 until active.pageCount) title to page else null
                }
                if (items.isEmpty()) { toast("请至少保留一个有效目录项"); return@setOnClickListener }
                runCatching {
                    synchronized(active.docLock) {
                        val outline = PDDocumentOutline()
                        items.forEach { (title, page) ->
                            val item = PDOutlineItem().apply {
                                this.title = title
                                destination = PDPageFitDestination().apply { setPage(active.doc.getPage(page)) }
                            }
                            outline.addLast(item)
                        }
                        outline.openNode()
                        active.doc.documentCatalog.documentOutline = outline
                        File(cacheDir, "bookmarks_${System.currentTimeMillis()}.pdf").also(active::saveTo)
                    }
                }.onSuccess { file ->
                    pendingExport = file
                    createPdfLauncher.launch(pdfName.removeSuffix(".pdf") + "_目录.pdf")
                    dialog.dismiss()
                }.onFailure { toast("生成失败：${it.message}") }
            }
        }
        dialog.show()
    }

    private fun showExtractPreview() {
        val active = session ?: run { toast("请先打开 PDF"); return }
        val selected = BooleanArray(active.pageCount)
        val checks = mutableListOf<android.widget.CompoundButton>()
        val grid = GridLayout(this).apply { columnCount = 2; setPadding(dp(8), dp(8), dp(8), dp(8)) }
        for (page in 0 until active.pageCount) {
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
                setPadding(dp(8), dp(8), dp(8), dp(4)); setBackgroundColor(colorOf(R.color.hi_surface))
            }
            val width = dp(140)
            val ratio = active.pageWidth(page) / active.pageHeight(page).coerceAtLeast(1f)
            val height = (width / ratio).toInt().coerceIn(dp(80), dp(200))
            val preview = ImageView(this).apply {
                scaleType = ImageView.ScaleType.FIT_CENTER; setBackgroundColor(Color.WHITE)
                layoutParams = LinearLayout.LayoutParams(width, height)
            }
            val check = CheckBox(this).apply {
                text = "第 ${page + 1} 页"; textSize = 12f
                setOnCheckedChangeListener { _, checked -> selected[page] = checked }
            }
            checks.add(check)
            card.addView(preview); card.addView(check)
            preview.setImageBitmap(runCatching { active.renderPage(page, width, height) }.getOrNull())
            grid.addView(card, GridLayout.LayoutParams().apply {
                width = 0; columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f)
                setMargins(dp(4), dp(4), dp(4), dp(4))
            })
        }
        val rangeInput = EditText(this).apply {
            hint = "页码范围，例如 1-3,5"; textSize = 14f; setSingleLine()
            setBackgroundResource(R.drawable.hi_input_bg)
            layoutParams = LinearLayout.LayoutParams(0, dp(44), 1f)
        }
        val rangeBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(12), dp(6), dp(12), dp(6))
            addView(rangeInput)
            addView(TextView(this@MainActivity).apply {
                text = "应用"; gravity = Gravity.CENTER; setTextColor(colorOf(R.color.hi_brand_500))
                setPadding(dp(12), 0, dp(4), 0)
                setOnClickListener {
                    val indexes = rangeInput.text.toString().split(",", "，").flatMap { part ->
                        val ends = part.trim().split("-")
                        val start = ends.firstOrNull()?.trim()?.toIntOrNull()
                        val end = ends.getOrNull(1)?.trim()?.toIntOrNull() ?: start
                        if (start == null || end == null) emptyList() else (minOf(start, end)..maxOf(start, end)).toList()
                    }.filter { it in 1..active.pageCount }.toSet()
                    if (indexes.isEmpty()) { toast("请输入有效页码范围"); return@setOnClickListener }
                    checks.forEachIndexed { index, check -> check.isChecked = index + 1 in indexes }
                }
            })
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(rangeBar)
            addView(ScrollView(this@MainActivity).apply {
                addView(grid)
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, dp(440))
            })
        }
        val dialog = AlertDialog.Builder(this).setTitle("PDF 节选预览 · ${active.pageCount} 页")
            .setView(content).setNeutralButton("清除选择", null).setNegativeButton("取消", null)
            .setPositiveButton("导出所选页面", null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener { checks.forEach { it.isChecked = false } }
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val pages = selected.indices.filter { selected[it] }
                if (pages.isEmpty()) { toast("请先选择要导出的页面"); return@setOnClickListener }
                runCatching {
                    val out = File(cacheDir, "extract_${System.currentTimeMillis()}.pdf")
                    synchronized(active.docLock) {
                        PDDocument().use { result ->
                            pages.forEach { result.importPage(active.doc.getPage(it)) }
                            result.save(out)
                        }
                    }
                    out
                }.onSuccess { file ->
                    pendingExport = file
                    createPdfLauncher.launch(pdfName.removeSuffix(".pdf") + "_节选.pdf")
                    dialog.dismiss()
                }.onFailure { toast("节选失败：${it.message}") }
            }
        }
        dialog.show()
    }

    private fun queryDisplayName(uri: Uri): String? = runCatching {
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (c.moveToFirst() && idx >= 0) c.getString(idx) else null
        }
    }.getOrNull()

    private fun save() {
        val s = session ?: return
        val uri = pdfUri
        if (!dirty) {
            toast("没有未保存的修改")
            return
        }
        if (uri == null) return
        try {
            val out = File(cacheDir, "save_tmp.pdf")
            s.saveTo(out)
            contentResolver.openOutputStream(uri, "wt")?.use { os ->
                out.inputStream().use { it.copyTo(os) }
            } ?: error("无法写入原文件")
            dirty = false
            updateStatus()
            toast("已保存到原文件")
        } catch (e: Exception) {
            AlertDialog.Builder(this)
                .setTitle("保存失败")
                .setMessage("${e.message}\n是否另存为副本？")
                .setPositiveButton("另存为") { _, _ ->
                    createPdfLauncher.launch(pdfName.removeSuffix(".pdf") + "_标注.pdf")
                }
                .setNegativeButton("取消", null)
                .show()
        }
    }

    private fun saveAs(uri: Uri) {
        val s = session ?: return
        try {
            val out = File(cacheDir, "saveas_tmp.pdf")
            s.saveTo(out)
            contentResolver.openOutputStream(uri, "wt")?.use { os ->
                out.inputStream().use { it.copyTo(os) }
            } ?: error("无法写入")
            toast("已导出副本")
        } catch (e: Exception) {
            toast("导出失败：${e.message}")
        }
    }

    private fun confirmDiscard(onContinue: () -> Unit) {
        if (!dirty) {
            onContinue()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("未保存的修改")
            .setMessage("当前 PDF 有未保存的标注或留言。")
            .setPositiveButton("保存") { _, _ ->
                val uri = pdfUri
                if (uri == null) { onContinue(); return@setPositiveButton }
                try {
                    val out = File(cacheDir, "save_tmp.pdf")
                    session?.saveTo(out)
                    contentResolver.openOutputStream(uri, "wt")?.use { os ->
                        out.inputStream().use { it.copyTo(os) }
                    }
                    dirty = false
                } catch (_: Exception) { }
                onContinue()
            }
            .setNegativeButton("放弃修改") { _, _ -> onContinue() }
            .setNeutralButton("取消", null)
            .show()
    }

    // ---- 页面 / 工具 ----

    private fun showPage(index: Int) {
        val s = session ?: return
        pageView.showPage(index.coerceIn(0, s.pageCount - 1))
        updatePageLabel()
        refreshHighlights()
    }

    private fun updatePageLabel() {
        val s = session ?: return
        pageLabel.text = "${pageView.pageIndex + 1} / ${s.pageCount}"
    }

    private fun updateStatus() {
        titleText.text = pdfName.removeSuffix(".pdf")
        statusText.text = if (dirty) "有未保存修改" else "已保存"
    }

    private fun setTool(t: Tool) {
        currentTool = t
        if (t != Tool.SELECT_STROKE) pageView.clearSelection()
        pageView.tool = t
        toolButtons.forEach { (k, b) -> b.isSelected = (k == t) }
    }

    private fun updateColorBtnText() {
        val (c, name) = colors[colorIdx]
        colorBtn.imageTintList = ColorStateList.valueOf(c)
        colorBtn.contentDescription = "笔色：$name"
        colorBtn.tooltipText = "笔色：$name"
    }

    private fun updateSelColorBtnText() {
        val (c, name) = colors[selColorIdx]
        selColorBtn.imageTintList = ColorStateList.valueOf(c)
        selColorBtn.contentDescription = "所选笔画颜色：$name"
        selColorBtn.tooltipText = "所选笔画颜色：$name"
    }

    private fun cycleColor() {
        colorIdx = (colorIdx + 1) % colors.size
        pageView.penColor = colors[colorIdx].first
        updateColorBtnText()
    }

    private fun cycleSelectionColor() {
        selColorIdx = (selColorIdx + 1) % colors.size
        updateSelColorBtnText()
        pageView.colorSelection(colors[selColorIdx].first)
    }

    private fun undo() {
        val s = session ?: return
        if (s.undo()) {
            dirty = true
            updateStatus()
            pageView.refresh()
        } else {
            toast("没有可撤销的操作")
        }
    }

    // ---- 留言 ----

    private fun noteInput(text: String = ""): Pair<FrameLayout, EditText> {
        val input = EditText(this).apply {
            setText(text)
            hint = "留言内容"
            textSize = 14f
            setTextColor(colorOf(R.color.hi_text_primary))
            setHintTextColor(colorOf(R.color.hi_text_tertiary))
            setBackgroundResource(R.drawable.hi_input_bg)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            minLines = 3
            gravity = Gravity.TOP
        }
        val box = FrameLayout(this).apply {
            addView(input, FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT).apply {
                setMargins(dp(20), dp(8), dp(20), 0)
            })
        }
        return box to input
    }

    private fun placeNoteDialog(x: Float, y: Float) {
        val s = session ?: return
        val (box, input) = noteInput()
        val dlg = AlertDialog.Builder(this)
            .setTitle("新建留言")
            .setView(box)
            .setPositiveButton("确定") { _, _ ->
                val text = input.text.toString().trim()
                if (text.isNotEmpty()) {
                    s.addNote(pageView.pageIndex, NoteMark(x, y, text))
                    dirty = true
                    updateStatus()
                    pageView.refresh()
                }
            }
            .setNegativeButton("取消", null)
            .show()
        // 键盘弹出时对话框上移，避免按钮被输入法遮住
        dlg.window?.setSoftInputMode(
            android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
    }

    private fun editNoteDialog(note: NoteMark) {
        val s = session ?: return
        val (box, input) = noteInput(note.text)
        val dlg = AlertDialog.Builder(this)
            .setTitle("编辑留言")
            .setView(box)
            .setPositiveButton("保存") { _, _ ->
                val text = input.text.toString().trim()
                if (text.isNotEmpty() && text != note.text) {
                    note.text = text
                    note.saved = false
                    dirty = true
                    updateStatus()
                    pageView.refresh()
                }
            }
            .setNeutralButton("删除") { _, _ ->
                s.removeNote(pageView.pageIndex, note)
                dirty = true
                updateStatus()
                pageView.refresh()
            }
            .setNegativeButton("取消", null)
            .show()
        dlg.window?.setSoftInputMode(
            android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
    }

    // ---- 查找 ----

    private fun toggleSearch() {
        searchRow.visibility =
            if (searchRow.visibility == View.GONE) View.VISIBLE else View.GONE
        if (searchRow.visibility == View.VISIBLE) searchInput.requestFocus()
    }

    private fun startSearch() {
        val s = session ?: return
        val needle = searchInput.text.toString().trim()
        if (needle.isEmpty()) return
        searchThread?.interrupt()
        searchCancelled = true
        searchCancelled = false
        hits = emptyList()
        currentHit = -1
        pageView.setHighlights(emptyList())
        searchCount.text = "查找中…"
        val cancelled = { searchCancelled || Thread.currentThread().isInterrupted }
        val thread = Thread {
            try {
                val result = PdfSearcher(s.doc, s.docLock).search(
                    needle,
                    onProgress = { done, total ->
                        runOnUiThread { searchCount.text = "$done/$total 页" }
                    },
                    isCancelled = cancelled)
                runOnUiThread {
                    hits = result
                    if (result.isEmpty()) {
                        searchCount.text = "无结果"
                    } else {
                        searchCount.text = "${result.size} 条"
                        showHit(0)
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { searchCount.text = "失败：${e.message?.take(30)}" }
            }
        }
        searchThread = thread
        thread.start()
    }

    private fun showHit(index: Int) {
        if (hits.isEmpty()) return
        currentHit = ((index % hits.size) + hits.size) % hits.size
        val hit = hits[currentHit]
        if (hit.page != pageView.pageIndex) {
            pageView.showPage(hit.page)
        }
        updatePageLabel()
        refreshHighlights()
        // 滚动到命中附近（top-down 坐标）
        pageView.post { pageView.scrollToRect(hit.rect) }
    }

    private fun stepHit(delta: Int) {
        if (hits.isNotEmpty()) showHit(currentHit + delta)
    }

    private fun refreshHighlights() {
        val items = mutableListOf<Pair<RectF, Boolean>>()
        hits.forEachIndexed { i, h ->
            if (h.page == pageView.pageIndex) items.add(h.rect to (i == currentHit))
        }
        pageView.setHighlights(items)
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    override fun onDestroy() {
        searchCancelled = true
        searchThread?.interrupt()
        session?.close()
        super.onDestroy()
    }
}
