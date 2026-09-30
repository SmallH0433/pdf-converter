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
    private var twoFingerPan = false    // 双指平移/缩放中
    private var tapMoved = false
    private var lastPanX = 0f
    private var lastPanY = 0f
    private var downX = 0f
    private var downY = 0f
    private var downTime = 0L

    // ---- 笔画选择（框选/圈选） ----
    var selModeRect = true              // true=框选（矩形） false=圈选（套索）
    private val selPath = mutableListOf<Pair<Float, Float>>()  // 拖拽路径（视图 px）
    private val selectedStrokes = mutableListOf<Stroke>()
    private var selBBox: RectF? = null  // PDF 坐标（y 向上；top=minY, bottom=maxY）
    private var movingSel = false
    private var moveLastX = 0f
    private var moveLastY = 0f
    var onSelectionChanged: ((Int) -> Unit)? = null
    val hasSelection: Boolean get() = selectedStrokes.isNotEmpty()

    // ---- 选区手柄：四角缩放 + 顶部旋转 ----
    private enum class SelHandle { NONE, TL, TR, BL, BR, ROTATE }
    private var activeHandle = SelHandle.NONE
    private var handleAnchorX = 0f      // PDF 坐标：缩放=对角锚点，旋转=包围盒中心
    private var handleAnchorY = 0f
    private var handleLastDist = 0f
    private var handleLastAngle = 0.0
    private var rotateIcon: Bitmap? = null

    private val handleRadiusPx get() = 11f * resources.displayMetrics.density
    private val handleTouchPx get() = 26f * resources.displayMetrics.density
    private val rotateOffsetPx get() = 34f * resources.displayMetrics.density

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
        clearSelection()
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

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        // 宽度变化（转屏/分屏，此时尺寸已是新值）：重新适应宽度；首次布局由 showPage 处理
        if (oldw > 0 && w != oldw && session != null) fitToWidth()
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
        // 画布底色：HiUI gray-300，白页在其上有清晰对比
        canvas.drawColor(Color.rgb(230, 232, 235))
        val s = session
        val bmp = bitmap
        if (s == null || bmp == null) {
            val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.rgb(145, 149, 158) // HiUI gray-600
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
        drawSelectionOverlay(canvas, s.pageHeight(pageIndex))
        canvas.restore()
        drawSelectionHandles(canvas)
    }

    /** 选区手柄：四角缩放圆点 + 顶部旋转圆钮（视图坐标绘制，大小不随缩放变化）。 */
    private fun drawSelectionHandles(canvas: Canvas) {
        if (!hasSelection) return
        val r = selViewRect() ?: return
        val density = resources.displayMetrics.density
        val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = Color.WHITE
        }
        val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 2f * density
            color = Color.rgb(38, 96, 255) // HiUI brandblue-500
        }
        // 顶部旋转手柄：连接线 + 圆钮 + 图标
        val (rcx, rcy) = rotateHandleCenter(r)
        canvas.drawLine(r.centerX(), r.top, rcx, rcy + handleRadiusPx, stroke)
        canvas.drawCircle(rcx, rcy, handleRadiusPx, fill)
        canvas.drawCircle(rcx, rcy, handleRadiusPx, stroke)
        rotateIconBitmap()?.let { icon ->
            val half = handleRadiusPx * 0.75f
            canvas.drawBitmap(icon, null,
                RectF(rcx - half, rcy - half, rcx + half, rcy + half), null)
        }
        // 四角缩放手柄
        canvas.drawCircle(r.left, r.top, handleRadiusPx, fill)
        canvas.drawCircle(r.left, r.top, handleRadiusPx, stroke)
        canvas.drawCircle(r.right, r.top, handleRadiusPx, fill)
        canvas.drawCircle(r.right, r.top, handleRadiusPx, stroke)
        canvas.drawCircle(r.left, r.bottom, handleRadiusPx, fill)
        canvas.drawCircle(r.left, r.bottom, handleRadiusPx, stroke)
        canvas.drawCircle(r.right, r.bottom, handleRadiusPx, fill)
        canvas.drawCircle(r.right, r.bottom, handleRadiusPx, stroke)
    }

    private fun rotateIconBitmap(): Bitmap? {
        rotateIcon?.let { return it }
        val d = androidx.appcompat.content.res.AppCompatResources.getDrawable(
            context, R.drawable.ic_rotate) ?: return null
        val size = (48 * resources.displayMetrics.density).toInt()
        val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        d.setBounds(0, 0, size, size)
        d.draw(c)
        rotateIcon = bmp
        return bmp
    }

    // ---- 笔画选择（框选/圈选） ----

    private fun drawSelectionOverlay(canvas: Canvas, pageH: Float) {
        val dash = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            color = Color.rgb(38, 96, 255) // HiUI brandblue-500
            strokeWidth = 1.5f
            pathEffect = android.graphics.DashPathEffect(floatArrayOf(8f, 6f), 0f)
        }
        // 选中包围盒（PDF y 向上 → top-down 翻转）
        selBBox?.let { b ->
            canvas.drawRect(RectF(b.left, pageH - b.bottom, b.right, pageH - b.top), dash)
        }
        // 拖拽中的选择框 / 套索（selPath 为视图 px，需换算到 top-down 页面坐标）
        if (selPath.size >= 2) {
            val scale = totalScale()
            fun vx(v: Float) = (v - offsetX) / scale
            fun vy(v: Float) = (v - offsetY) / scale
            if (selModeRect) {
                val (x0, y0) = selPath.first()
                val (x1, y1) = selPath.last()
                canvas.drawRect(RectF(minOf(vx(x0), vx(x1)), minOf(vy(y0), vy(y1)),
                                      maxOf(vx(x0), vx(x1)), maxOf(vy(y0), vy(y1))), dash)
            } else {
                for (i in 1 until selPath.size) {
                    canvas.drawLine(vx(selPath[i - 1].first), vy(selPath[i - 1].second),
                                    vx(selPath[i].first), vy(selPath[i].second), dash)
                }
            }
        }
    }

    private fun beginSelectOrMove(vx: Float, vy: Float) {
        val (px, py) = viewToPdf(vx, vy)
        // 手柄优先（角手柄骑跨在包围盒边缘，须先于盒内拖动判断）
        val h = hitHandle(vx, vy)
        if (h != SelHandle.NONE) {
            beginHandleDrag(h, px, py)
            return
        }
        val b = selBBox
        if (b != null && px >= b.left && px <= b.right && py >= b.top && py <= b.bottom) {
            movingSel = true   // 点在包围盒内：拖动选区
            moveLastX = vx
            moveLastY = vy
        } else {
            clearSelection()
            selPath.add(vx to vy)
        }
    }

    /** 选区包围盒的视图坐标矩形（PDF y 向上 → 视图 y 向下）。 */
    private fun selViewRect(): RectF? {
        val s = session ?: return null
        val b = selBBox ?: return null
        val scale = totalScale()
        val pageH = s.pageHeight(pageIndex)
        return RectF(offsetX + b.left * scale, offsetY + (pageH - b.bottom) * scale,
                     offsetX + b.right * scale, offsetY + (pageH - b.top) * scale)
    }

    private fun rotateHandleCenter(r: RectF) = r.centerX() to (r.top - rotateOffsetPx)

    private fun hitHandle(vx: Float, vy: Float): SelHandle {
        val r = selViewRect() ?: return SelHandle.NONE
        val (rcx, rcy) = rotateHandleCenter(r)
        if (kotlin.math.hypot(vx - rcx, vy - rcy) <= handleTouchPx) return SelHandle.ROTATE
        val corners = arrayOf(
            SelHandle.TL to (r.left to r.top), SelHandle.TR to (r.right to r.top),
            SelHandle.BL to (r.left to r.bottom), SelHandle.BR to (r.right to r.bottom))
        for ((h, pos) in corners) {
            if (kotlin.math.hypot(vx - pos.first, vy - pos.second) <= handleTouchPx) return h
        }
        return SelHandle.NONE
    }

    private fun beginHandleDrag(h: SelHandle, px: Float, py: Float) {
        val b = selBBox ?: return
        activeHandle = h
        if (h == SelHandle.ROTATE) {
            handleAnchorX = b.centerX()
            handleAnchorY = b.centerY()
            handleLastAngle = kotlin.math.atan2(py - handleAnchorY, px - handleAnchorX).toDouble()
        } else {
            // 视图角 ↔ PDF 角：视图顶部 = PDF 大 y（b.bottom）；锚点取对角
            handleAnchorX = if (h == SelHandle.TL || h == SelHandle.BL) b.right else b.left
            handleAnchorY = if (h == SelHandle.TL || h == SelHandle.TR) b.top else b.bottom
            handleLastDist = kotlin.math.hypot(px - handleAnchorX, py - handleAnchorY)
                .coerceAtLeast(1f)
        }
    }

    private fun dragHandle(vx: Float, vy: Float) {
        val (px, py) = viewToPdf(vx, vy)
        if (activeHandle == SelHandle.ROTATE) {
            val ang = kotlin.math.atan2(py - handleAnchorY, px - handleAnchorX).toDouble()
            val delta = ang - handleLastAngle
            handleLastAngle = ang
            if (delta != 0.0) rotateSelectionRad(delta.toFloat())
        } else {
            val dist = kotlin.math.hypot(px - handleAnchorX, py - handleAnchorY)
            val factor = (dist / handleLastDist).coerceIn(0.05f, 20f)
            handleLastDist = dist
            if (factor != 1f) scaleSelectionFrom(handleAnchorX, handleAnchorY, factor)
        }
    }

    /** 手柄拖动结束：统一把改动写入文档模型（拖动过程中不置脏，避免频繁回调）。 */
    private fun finishHandleDrag() {
        activeHandle = SelHandle.NONE
        val s = session ?: return
        for (stroke in selectedStrokes) s.markModified(pageIndex, stroke)
        if (selectedStrokes.isNotEmpty()) onChanged?.invoke()
    }

    private fun moveSelectionBy(vx: Float, vy: Float) {
        val scale = totalScale()
        val dpx = (vx - moveLastX) / scale
        val dpy = -(vy - moveLastY) / scale   // 视图 y 向下 → PDF y 向上取负
        moveLastX = vx
        moveLastY = vy
        for (s in selectedStrokes) {
            for (i in s.points.indices) {
                val (x, y, p) = s.points[i]
                s.points[i] = Triple(x + dpx, y + dpy, p)
            }
        }
        selBBox?.let {
            it.left += dpx
            it.right += dpx
            it.top += dpy
            it.bottom += dpy
        }
        invalidate()
    }

    private fun finishSelect() {
        val s = session ?: return
        if (selPath.size < 2) {
            selPath.clear()
            return
        }
        val pdfPts = selPath.map { (vx, vy) -> viewToPdf(vx, vy) }
        selPath.clear()
        val hit: (Float, Float) -> Boolean
        if (selModeRect) {
            val xs = pdfPts.map { it.first }
            val ys = pdfPts.map { it.second }
            val l = xs.min(); val r = xs.max()
            val b = ys.min(); val t = ys.max()
            if (r - l < 2 && t - b < 2) return
            hit = { x, y -> x in l..r && y in b..t }
        } else {
            hit = { x, y -> pointInPolygon(x, y, pdfPts) }
        }
        selectedStrokes.clear()
        for (stroke in s.strokesOf(pageIndex)) {
            if (stroke.points.any { (x, y, _) -> hit(x, y) }) {
                selectedStrokes.add(stroke)
            }
        }
        recomputeSelBBox()
        onSelectionChanged?.invoke(selectedStrokes.size)
        invalidate()
    }

    private fun recomputeSelBBox() {
        selBBox = if (selectedStrokes.isEmpty()) null else {
            val xs = selectedStrokes.flatMap { s -> s.points.map { it.first } }
            val ys = selectedStrokes.flatMap { s -> s.points.map { it.second } }
            RectF(xs.min(), ys.min(), xs.max(), ys.max())
        }
    }

    /** 对选中笔画应用坐标变换 fn(x, y) -> (x', y')。 */
    fun transformSelection(fn: (Float, Float) -> Pair<Float, Float>) {
        val s = session ?: return
        for (stroke in selectedStrokes) {
            for (i in stroke.points.indices) {
                val (x, y, p) = stroke.points[i]
                val (nx, ny) = fn(x, y)
                stroke.points[i] = Triple(nx, ny, p)
            }
            s.markModified(pageIndex, stroke)
        }
        recomputeSelBBox()
        onChanged?.invoke()
        invalidate()
    }

    fun scaleSelection(factor: Float) {
        val b = selBBox ?: return
        val cx = b.centerX()
        val cy = b.centerY()
        transformSelection { x, y -> cx + (x - cx) * factor to cy + (y - cy) * factor }
    }

    /** 拖动手柄期间的静默变换：只改坐标、重算包围盒、刷新，不置脏（结束时统一提交）。 */
    private fun applySelTransform(fn: (Float, Float) -> Pair<Float, Float>) {
        for (stroke in selectedStrokes) {
            for (i in stroke.points.indices) {
                val (x, y, p) = stroke.points[i]
                val (nx, ny) = fn(x, y)
                stroke.points[i] = Triple(nx, ny, p)
            }
        }
        recomputeSelBBox()
        invalidate()
    }

    private fun scaleSelectionFrom(ax: Float, ay: Float, factor: Float) {
        applySelTransform { x, y -> ax + (x - ax) * factor to ay + (y - ay) * factor }
    }

    private fun rotateSelectionRad(rad: Float) {
        val b = selBBox ?: return
        val cosA = kotlin.math.cos(rad)
        val sinA = kotlin.math.sin(rad)
        val cx = b.centerX()
        val cy = b.centerY()
        applySelTransform { x, y ->
            val dx = x - cx
            val dy = y - cy
            cx + dx * cosA - dy * sinA to cy + dx * sinA + dy * cosA
        }
    }

    fun rotateSelection(degrees: Float) {
        val b = selBBox ?: return
        val a = Math.toRadians(degrees.toDouble())
        val cosA = kotlin.math.cos(a).toFloat()
        val sinA = kotlin.math.sin(a).toFloat()
        val cx = b.centerX()
        val cy = b.centerY()
        transformSelection { x, y ->
            val dx = x - cx
            val dy = y - cy
            cx + dx * cosA - dy * sinA to cy + dx * sinA + dy * cosA
        }
    }

    fun colorSelection(color: Int) {
        val s = session ?: return
        for (stroke in selectedStrokes) {
            stroke.color = color
            s.markModified(pageIndex, stroke)
        }
        onChanged?.invoke()
        invalidate()
    }

    fun deleteSelection() {
        val s = session ?: return
        for (stroke in selectedStrokes) {
            s.markModified(pageIndex, stroke)
            s.strokes[pageIndex]?.remove(stroke)
        }
        clearSelection()
        onChanged?.invoke()
    }

    fun clearSelection() {
        val had = selectedStrokes.isNotEmpty()
        selectedStrokes.clear()
        selBBox = null
        selPath.clear()
        movingSel = false
        activeHandle = SelHandle.NONE
        if (had) onSelectionChanged?.invoke(0)
        invalidate()
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
                            Tool.SELECT_STROKE -> beginSelectOrMove(event.x, event.y)
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
                            // 画笔/橡皮：单指书写/擦除
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
                            // 选择/留言：单指只用于轻点交互，不拖动页面
                            // （所有工具统一：单指=使用工具，双指=拖动/缩放页面）
                            Tool.SELECT_STROKE -> beginSelectOrMove(event.x, event.y)
                            else -> {}
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
                selPath.clear()
                movingSel = false
                activeHandle = SelHandle.NONE
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
                if (activeHandle != SelHandle.NONE) {
                    dragHandle(event.x, event.y)
                    return true
                }
                if (movingSel) {
                    moveSelectionBy(event.x, event.y)
                    return true
                }
                if (selPath.isNotEmpty()) {
                    selPath.add(event.x to event.y)
                    invalidate()
                    return true
                }
                for (i in 0 until event.pointerCount) {
                    val id = event.getPointerId(i)
                    if (id == drawPointer) {
                        if (erasingActive) {
                            eraseAt(event.getX(i), event.getY(i))
                        } else {
                            extendStroke(event, i)
                        }
                    }
                }
            }
            MotionEvent.ACTION_POINTER_UP -> {
                if (twoFingerPan && event.pointerCount - 1 < 2) {
                    twoFingerPan = false
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                val id = event.getPointerId(event.actionIndex)
                if (id == drawPointer) {
                    if (!erasingActive) finishStroke()
                    drawPointer = -1
                    erasingActive = false
                }
                // 选区变换结束：手柄（缩放/旋转）或盒内拖动，把改动写入文档模型
                if (activeHandle != SelHandle.NONE) {
                    finishHandleDrag()
                } else if (movingSel) {
                    movingSel = false
                    val s2 = session
                    if (s2 != null) {
                        for (stroke in selectedStrokes) s2.markModified(pageIndex, stroke)
                        if (selectedStrokes.isNotEmpty()) onChanged?.invoke()
                    }
                } else if (selPath.isNotEmpty()) {
                    finishSelect()
                }
                // 轻点（选择/留言模式、未拖动）：便签编辑 / 留言放置
                val dt = event.eventTime - downTime
                val dist = kotlin.math.hypot(event.x - downX, event.y - downY)
                if (dt < 400 && dist < 36f && !tapMoved && !twoFingerPan &&
                    (tool == Tool.SELECT || tool == Tool.NOTE) &&
                    event.getToolType(event.actionIndex) != MotionEvent.TOOL_TYPE_STYLUS) {
                    handleTap(event.x, event.y)
                }
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
