package com.smallh.pdfreader

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View

/**
 * 单页画布：渲染页面位图，叠加手写笔画（压感）、留言标记、搜索高亮。
 *
 * 手写笔（TOOL_TYPE_STYLUS）在笔模式下书写、橡皮端（TOOL_TYPE_ERASER）擦除；
 * 手指单指平移、双指捏合缩放（安卓交互约定：手指导航、手写笔书写）。
 * 留言/选择模式下，点击放置或编辑便签。
 *
 * 坐标系：笔画/便签用 PDF 用户坐标（y 向上）；搜索高亮用 top-down 坐标（y 向下）。
 */
class PageView(context: Context) : View(context) {

    var session: PdfSession? = null
    var pageIndex = 0
        private set
    var tool = Tool.PEN
        set(value) { field = value; currentStroke = null }

    var penColor = Color.rgb(229, 57, 53)
    var penWidthPt = 3f

    var onChanged: (() -> Unit)? = null          // 标注增删改（置脏）
    var onNoteTap: ((NoteMark) -> Unit)? = null  // 点击已有便签
    var onNotePlace: ((Float, Float) -> Unit)? = null // 空白处放置便签（PDF 坐标）
    var onPageRendered: (() -> Unit)? = null

    private var bitmap: Bitmap? = null
    private var bmpPageW = 1f  // 位图对应的页宽（PDF 点）
    private var bmpPageH = 1f

    private var fitScale = 1f
    private var zoom = 1f
    private var offsetX = 0f
    private var offsetY = 0f

    private val currentStrokePoints = mutableListOf<Triple<Float, Float, Float>>()
    private var currentStroke: Stroke? = null
    private var drawPointer = -1        // 正在书写/擦除的指针（手写笔或手指）
    private var drawingWithFinger = false
    private var erasingActive = false
    private var stylusDown = false      // 手写笔在屏（手掌排斥：忽略手指）
    private var panPointer = -1         // 单指平移（选择/留言模式）
    private var twoFingerPan = false    // 双指平移/缩放中
    private var tapMoved = false
    private var lastPanX = 0f
    private var lastPanY = 0f
    private var downX = 0f
    private var downY = 0f
    private var downTime = 0L

    private val highlights = mutableListOf<Pair<RectF, Boolean>>() // top-down 坐标, 是否当前条

    private val renderRunnable = Runnable { doRender() }
    private val scaleDetector = ScaleGestureDetector(context,
        object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
            override fun onScale(d: ScaleGestureDetector): Boolean {
                zoom = (zoom * d.scaleFactor).coerceIn(0.3f, 8f)
                clampOffsets()
                scheduleRender()
                invalidate()
                return true
            }
        })

    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val notePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.rgb(255, 213, 79)
    }
    private val noteBorderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 1.2f
        color = Color.rgb(120, 90, 0)
    }

    // ---- 页面加载与渲染 ----

    fun showPage(index: Int) {
        val s = session ?: return
        pageIndex = index.coerceIn(0, s.pageCount - 1)
        currentStroke = null
        currentStrokePoints.clear()
        fitToWidth()
    }

    fun fitToWidth() {
        val s = session ?: return
        if (width == 0) {
            post { fitToWidth() }
            return
        }
        zoom = 1f
        fitScale = (width - paddingLeft - paddingRight) / s.pageWidth(pageIndex)
        offsetX = paddingLeft.toFloat()
        offsetY = paddingTop + 8f
        scheduleRender()
        invalidate()
    }

    private fun totalScale() = fitScale * zoom

    private fun scheduleRender() {
        removeCallbacks(renderRunnable)
        postDelayed(renderRunnable, 120)
    }

    private fun doRender() {
        val s = session ?: return
        val scale = totalScale()
        val w = (s.pageWidth(pageIndex) * scale).toInt().coerceAtMost(4096)
        val h = (s.pageHeight(pageIndex) * scale).toInt().coerceAtMost(4096)
        bitmap = s.renderPage(pageIndex, w, h)
        bmpPageW = s.pageWidth(pageIndex)
        bmpPageH = s.pageHeight(pageIndex)
        invalidate()
        onPageRendered?.invoke()
    }

    fun setHighlights(items: List<Pair<RectF, Boolean>>) {
        highlights.clear()
        highlights.addAll(items)
        invalidate()
    }

    // ---- 坐标换算：view px ↔ 页面坐标（top-down, PDF 点） ----

    private fun viewToPage(vx: Float, vy: Float): Pair<Float, Float> {
        val scale = totalScale()
        return (vx - offsetX) / scale to (vy - offsetY) / scale
    }

    /** view px → PDF 用户坐标（y 向上）。 */
    private fun viewToPdf(vx: Float, vy: Float): Pair<Float, Float> {
        val (px, py) = viewToPage(vx, vy)
        val s = session ?: return px to py
        return px to s.pageHeight(pageIndex) - py
    }

    // ---- 绘制 ----

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.rgb(96, 96, 96))
        val s = session
        val bmp = bitmap
        if (s == null || bmp == null) {
            val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.LTGRAY
                textSize = 42f
                textAlign = Paint.Align.CENTER
            }
            canvas.drawText("打开或选择 PDF 开始阅读", width / 2f, height / 2f, p)
            return
        }
        val scale = totalScale()
        // 位图
        val bmpScale = Paint(Paint.FILTER_BITMAP_FLAG)
        val dest = RectF(offsetX, offsetY,
                         offsetX + bmpPageW * scale, offsetY + bmpPageH * scale)
        canvas.drawBitmap(bmp, null, dest, bmpScale)

        canvas.save()
        canvas.translate(offsetX, offsetY)
        canvas.scale(scale, scale) // 之后都在 top-down 页面坐标（PDF 点）中绘制

        // 搜索高亮（top-down 坐标直接使用）
        for ((rect, current) in highlights) {
            val p = Paint().apply {
                color = if (current) 0x82FF8C00.toInt() else 0x6EFFF59D.toInt()
            }
            canvas.drawRect(rect, p)
        }
        // 已保存与进行中的笔画（PDF y 向上 → top-down 翻转）
        for (stroke in s.strokesOf(pageIndex)) {
            drawStroke(canvas, stroke, s.pageHeight(pageIndex))
        }
        currentStroke?.let { drawStroke(canvas, it, s.pageHeight(pageIndex)) }
        // 留言标记
        for (note in s.notesOf(pageIndex)) {
            val ny = s.pageHeight(pageIndex) - note.y
            val r = RectF(note.x - 8, ny - 8, note.x + 8, ny + 8)
            canvas.drawRoundRect(r, 3f, 3f, notePaint)
            canvas.drawRoundRect(r, 3f, 3f, noteBorderPaint)
            val tp = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.rgb(120, 90, 0)
                textSize = 11f
                textAlign = Paint.Align.CENTER
            }
            canvas.drawText("留", note.x, ny + 4, tp)
        }
        canvas.restore()
    }

    private fun drawStroke(canvas: Canvas, stroke: Stroke, pageH: Float) {
        val pts = stroke.points
        if (pts.isEmpty()) return
        strokePaint.color = stroke.color
        if (pts.size == 1) {
            val (x, y, pr) = pts[0]
            strokePaint.strokeWidth = (stroke.widthPt * pr).coerceAtLeast(0.6f)
            canvas.drawPoint(x, pageH - y, strokePaint)
            return
        }
        for (i in 1 until pts.size) {
            val (x0, y0, p0) = pts[i - 1]
            val (x1, y1, p1) = pts[i]
            strokePaint.strokeWidth =
                (stroke.widthPt * (p0 + p1) / 2).coerceAtLeast(0.6f)
            canvas.drawLine(x0, pageH - y0, x1, pageH - y1, strokePaint)
        }
    }

    // ---- 触摸 ----

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        val s = session ?: return true
        scaleDetector.onTouchEvent(event)
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.x
                downY = event.y
                downTime = event.eventTime
                tapMoved = false
                val id = event.getPointerId(0)
                when (event.getToolType(0)) {
                    MotionEvent.TOOL_TYPE_STYLUS -> {
                        stylusDown = true
                        when (tool) {
                            Tool.PEN -> {
                                drawPointer = id
                                drawingWithFinger = false
                                erasingActive = false
                                beginStrokeAt(event.x, event.y, event.pressure)
                            }
                            Tool.ERASER -> {
                                drawPointer = id
                                erasingActive = true
                                eraseAt(event.x, event.y)
                            }
                            else -> handleTap(event.x, event.y)
                        }
                    }
                    MotionEvent.TOOL_TYPE_ERASER -> {
                        stylusDown = true
                        drawPointer = id
                        erasingActive = true
                        eraseAt(event.x, event.y)
                    }
                    else -> { // 手指
                        when (tool) {
                            // 画笔/橡皮：单指书写/擦除（双指才拖动页面）
                            Tool.PEN -> {
                                drawPointer = id
                                drawingWithFinger = true
                                erasingActive = false
                                beginStrokeAt(event.x, event.y, 0.6f)
                            }
                            Tool.ERASER -> {
                                drawPointer = id
                                erasingActive = true
                                eraseAt(event.x, event.y)
                            }
                            // 选择/留言：单指拖动页面，轻点交互
                            else -> {
                                panPointer = id
                                lastPanX = event.x
                                lastPanY = event.y
                            }
                        }
                    }
                }
            }
            MotionEvent.ACTION_POINTER_DOWN -> {
                // 第二指落下：手指起的笔画取消（视为想拖动），手写笔笔画落定保留
                if (drawPointer >= 0) {
                    if (!erasingActive) {
                        if (drawingWithFinger) {
                            currentStroke = null
                            currentStrokePoints.clear()
                            invalidate()
                        } else {
                            finishStroke()
                        }
                    }
                    drawPointer = -1
                    erasingActive = false
                }
                panPointer = -1
                tapMoved = true
                if (!stylusDown && event.pointerCount >= 2) { // 手写笔在屏时忽略手指（手掌排斥）
                    twoFingerPan = true
                    lastPanX = (event.getX(0) + event.getX(1)) / 2
                    lastPanY = (event.getY(0) + event.getY(1)) / 2
                }
            }
            MotionEvent.ACTION_MOVE -> {
                if (twoFingerPan && event.pointerCount >= 2) {
                    val mx = (event.getX(0) + event.getX(1)) / 2
                    val my = (event.getY(0) + event.getY(1)) / 2
                    offsetX += mx - lastPanX
                    offsetY += my - lastPanY
                    lastPanX = mx
                    lastPanY = my
                    clampOffsets()
                    invalidate()
                    return true
                }
                for (i in 0 until event.pointerCount) {
                    val id = event.getPointerId(i)
                    when (id) {
                        drawPointer -> {
                            if (erasingActive) {
                                eraseAt(event.getX(i), event.getY(i))
                            } else {
                                extendStroke(event, i)
                            }
                        }
                        panPointer -> {
                            val dx = event.getX(i) - lastPanX
                            val dy = event.getY(i) - lastPanY
                            offsetX += dx
                            offsetY += dy
                            lastPanX = event.getX(i)
                            lastPanY = event.getY(i)
                            if (kotlin.math.abs(dx) + kotlin.math.abs(dy) > 4f) tapMoved = true
                            clampOffsets()
                            invalidate()
                        }
                    }
                }
            }
            MotionEvent.ACTION_POINTER_UP -> {
                if (twoFingerPan && event.pointerCount - 1 < 2) {
                    twoFingerPan = false
                    // 剩余一指：选择/留言模式恢复单指平移
                    if (event.pointerCount - 1 == 1 &&
                        (tool == Tool.SELECT || tool == Tool.NOTE)) {
                        val idx = if (event.actionIndex == 0) 1 else 0
                        panPointer = event.getPointerId(idx)
                        lastPanX = event.getX(idx)
                        lastPanY = event.getY(idx)
                    }
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                val id = event.getPointerId(event.actionIndex)
                if (id == drawPointer) {
                    if (!erasingActive) finishStroke()
                    drawPointer = -1
                    erasingActive = false
                }
                // 轻点（选择/留言模式、未拖动）：便签编辑 / 留言放置
                val dt = event.eventTime - downTime
                val dist = kotlin.math.hypot(event.x - downX, event.y - downY)
                if (dt < 300 && dist < 24f && !tapMoved && !twoFingerPan &&
                    (tool == Tool.SELECT || tool == Tool.NOTE) &&
                    event.getToolType(event.actionIndex) != MotionEvent.TOOL_TYPE_STYLUS) {
                    handleTap(event.x, event.y)
                }
                panPointer = -1
                twoFingerPan = false
                stylusDown = false
            }
        }
        return true
    }

    private fun handleTap(vx: Float, vy: Float) {
        val s = session ?: return
        val (px, py) = viewToPdf(vx, vy)
        if (px < 0 || py < 0 || px > s.pageWidth(pageIndex) || py > s.pageHeight(pageIndex)) return
        val note = s.noteAt(pageIndex, px, py, 12f)
        if (note != null) {
            onNoteTap?.invoke(note)
        } else if (tool == Tool.NOTE) {
            onNotePlace?.invoke(px, py)
        }
    }

    private fun beginStrokeAt(x: Float, y: Float, pressure: Float) {
        currentStrokePoints.clear()
        currentStroke = Stroke(color = penColor, widthPt = penWidthPt)
        addStrokePoint(x, y, pressure.coerceIn(0.05f, 1f))
    }

    private fun extendStroke(event: MotionEvent, idx: Int) {
        val h = event.historySize
        for (j in 0 until h) {
            addStrokePoint(event.getHistoricalX(idx, j), event.getHistoricalY(idx, j),
                           event.getHistoricalPressure(idx, j))
        }
        addStrokePoint(event.getX(idx), event.getY(idx), event.getPressure(idx))
        invalidate()
    }

    private fun addStrokePoint(vx: Float, vy: Float, pressure: Float) {
        val (px, py) = viewToPdf(vx, vy)
        val stroke = currentStroke ?: return
        if (stroke.points.isNotEmpty()) {
            val (lx, ly, _) = stroke.points.last()
            if (kotlin.math.abs(px - lx) + kotlin.math.abs(py - ly) < 0.4f) return
        }
        stroke.points.add(Triple(px, py, pressure.coerceIn(0.05f, 1f)))
    }

    private fun finishStroke() {
        val s = session ?: return
        val stroke = currentStroke ?: return
        currentStroke = null
        if (stroke.points.isEmpty()) return
        if (stroke.points.size == 1) { // 单击成点
            val (x, y, pr) = stroke.points[0]
            stroke.points.add(Triple(x + 0.01f, y + 0.01f, pr))
        }
        s.addStroke(pageIndex, stroke)
        onChanged?.invoke()
        invalidate()
    }

    private fun eraseAt(vx: Float, vy: Float) {
        val s = session ?: return
        val (px, py) = viewToPdf(vx, vy)
        if (s.eraseNear(pageIndex, px, py, 8f)) {
            onChanged?.invoke()
            invalidate()
        }
    }

    private fun clampOffsets() {
        val s = session ?: return
        val scale = totalScale()
        val pageWpx = s.pageWidth(pageIndex) * scale
        val pageHpx = s.pageHeight(pageIndex) * scale
        offsetX = offsetX.coerceIn(width - pageWpx - 200f, 200f)
        offsetY = offsetY.coerceIn(height - pageHpx - 200f, 200f)
    }

    /** 供外部强制刷新（便签增删改后）。 */
    fun refresh() = invalidate()

    /** 滚动视图使 top-down 页面坐标矩形进入可视区（搜索跳转用）。 */
    fun scrollToRect(rect: RectF) {
        val scale = totalScale()
        offsetX = -rect.left * scale + width / 4f
        offsetY = -rect.top * scale + height / 3f
        clampOffsets()
        invalidate()
    }
}
