package com.smallh.pdfreader

import android.graphics.Color
import android.graphics.RectF
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.io.File

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
    private lateinit var colorBtn: Button
    private lateinit var modeBtn: Button
    private lateinit var selBar: LinearLayout
    private lateinit var selBarScroll: HorizontalScrollView
    private lateinit var selCountLabel: TextView
    private lateinit var selColorBtn: Button
    private var selColorIdx = 0

    private var session: PdfSession? = null
    private var pdfUri: Uri? = null
    private var pdfName = "未命名"
    private var dirty = false

    private val toolButtons = mutableMapOf<Tool, Button>()
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
            uri?.let { saveAs(it) }
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

    private fun handleViewIntent(intent: android.content.Intent?) {
        if (intent?.action == android.content.Intent.ACTION_VIEW) {
            intent.data?.let { openPdf(it) }
        }
    }

    // ---- UI ----

    private fun buildUi() {
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
        topBar.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(6), dp(8), dp(6))
            addView(primaryBtn("打开") { openPdfLauncher.launch(arrayOf("application/pdf")) })
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
            addView(ghostBtn("查找") { toggleSearch() })
            addView(ghostBtn("保存") { save() })
            addView(ghostBtn("另存") {
                createPdfLauncher.launch(pdfName.removeSuffix(".pdf") + "_标注.pdf")
            })
        })
        topBar.addView(divider())

        // 第二行：工具芯片（选中项高亮为品牌色浅底）
        topBar.addView(horizontalStrip {
            for ((t, name) in listOf(
                Tool.SELECT to "选择", Tool.PEN to "手写",
                Tool.NOTE to "留言", Tool.ERASER to "橡皮",
                Tool.SELECT_STROKE to "框选")) {
                val b = chip(name) { setTool(t) }
                toolButtons[t] = b
                addView(b)
            }
            // 框选 / 圈选切换（框选工具下生效）
            modeBtn = chip("模式：框") {
                pageView.selModeRect = !pageView.selModeRect
                modeBtn.text = if (pageView.selModeRect) "模式：框" else "模式：圈"
            }
            addView(modeBtn)
            colorBtn = chip("") { cycleColor() }
            addView(colorBtn)
            addView(chip("撤销") { undo() })
        })
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
            selColorBtn = chip("") { cycleSelectionColor() }
            addView(selColorBtn)
            addView(chip("放大") { pageView.scaleSelection(1.1f) })
            addView(chip("缩小") { pageView.scaleSelection(1 / 1.1f) })
            addView(chip("左旋") { pageView.rotateSelection(15f) })
            addView(chip("右旋") { pageView.rotateSelection(-15f) })
            addView(chip("删除") { pageView.deleteSelection() })
            addView(chip("完成") { pageView.clearSelection() })
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
            addView(tonalBtn("搜索") { startSearch() })
            addView(tonalBtn("↑") { stepHit(-1) })
            addView(tonalBtn("↓") { stepHit(1) })
            searchCount = TextView(this@MainActivity).apply {
                textSize = 13f
                setTextColor(colorOf(R.color.hi_text_secondary))
                setPadding(dp(12), 0, dp(4), 0)
            }
            addView(searchCount)
        }
        root.addView(searchRow)

        pageView = PageView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
            onChanged = { dirty = true; updateStatus() }
            onNoteTap = { note -> editNoteDialog(note) }
            onNotePlace = { x, y -> placeNoteDialog(x, y) }
            onPageRendered = { updatePageLabel() }
            onSelectionChanged = { count ->
                selCountLabel.text = "已选 $count 笔"
                selBarScroll.visibility = if (count > 0) View.VISIBLE else View.GONE
            }
        }
        root.addView(pageView)

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
            addView(tonalBtn("◀") { showPage(pageView.pageIndex - 1) })
            pageLabel = TextView(this@MainActivity).apply {
                text = "0 / 0"
                textSize = 13f
                gravity = Gravity.CENTER
                setTextColor(colorOf(R.color.hi_text_primary))
                setPadding(dp(8), 0, dp(8), 0)
            }
            addView(pageLabel)
            addView(tonalBtn("▶") { showPage(pageView.pageIndex + 1) })
            addView(ghostBtn("适应") { pageView.fitToWidth() })
        })
        root.addView(bottomBar)

        setContentView(root)
        updateColorBtnText()
        updateSelColorBtnText()
        setTool(Tool.PEN)
    }

    // ---- HiUI 风格控件工厂（圆角 8dp、14sp 正文、8dp 基准间距） ----

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun colorOf(res: Int) = ContextCompat.getColor(this, res)

    private fun divider(): View = View(this).apply {
        setBackgroundColor(colorOf(R.color.hi_divider))
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(1))
    }

    private fun horizontalStrip(build: LinearLayout.() -> Unit): HorizontalScrollView {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), 0, dp(8), dp(8))
            build()
        }
        return HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            addView(row)
        }
    }

    private fun baseBtn(text: String, onClick: () -> Unit): Button =
        Button(this).apply {
            this.text = text
            minWidth = 0
            minimumWidth = 0
            minHeight = 0
            minimumHeight = 0
            textSize = 14f
            isAllCaps = false
            stateListAnimator = null
            setPadding(dp(14), 0, dp(14), 0)
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, dp(36)).apply {
                marginStart = dp(8)
            }
        }

    private fun primaryBtn(text: String, onClick: () -> Unit): Button =
        baseBtn(text, onClick).apply {
            setBackgroundResource(R.drawable.hi_btn_primary)
            setTextColor(Color.WHITE)
        }

    private fun tonalBtn(text: String, onClick: () -> Unit): Button =
        baseBtn(text, onClick).apply {
            setBackgroundResource(R.drawable.hi_btn_tonal)
            setTextColor(colorOf(R.color.hi_text_primary))
        }

    private fun ghostBtn(text: String, onClick: () -> Unit): Button =
        baseBtn(text, onClick).apply {
            setBackgroundResource(R.drawable.hi_btn_ghost)
            setTextColor(colorOf(R.color.hi_brand_500))
        }

    private fun chip(text: String, onClick: () -> Unit): Button =
        baseBtn(text, onClick).apply {
            setBackgroundResource(R.drawable.hi_chip)
            setTextColor(ContextCompat.getColorStateList(
                this@MainActivity, R.color.hi_chip_text))
        }

    /** 文字前加一颗当前颜色的圆点，直观展示笔色。 */
    private fun colorDotLabel(prefix: String, c: Int, name: String): CharSequence =
        SpannableString("$prefix● $name").apply {
            setSpan(ForegroundColorSpan(c), prefix.length, prefix.length + 1,
                Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }

    // ---- 文件 ----

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
        if (t != Tool.SELECT_STROKE) pageView.clearSelection()
        pageView.tool = t
        toolButtons.forEach { (k, b) -> b.isSelected = (k == t) }
    }

    private fun updateColorBtnText() {
        val (c, name) = colors[colorIdx]
        colorBtn.text = colorDotLabel("笔色 ", c, name)
    }

    private fun updateSelColorBtnText() {
        val (c, name) = colors[selColorIdx]
        selColorBtn.text = colorDotLabel("改色 ", c, name)
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
