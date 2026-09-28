package com.smallh.pdfreader

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.RectF
import android.os.ParcelFileDescriptor
import android.graphics.pdf.PdfRenderer
import com.tom_roush.pdfbox.android.PDFBoxResourceLoader
import com.tom_roush.pdfbox.cos.COSArray
import com.tom_roush.pdfbox.cos.COSDictionary
import com.tom_roush.pdfbox.cos.COSFloat
import com.tom_roush.pdfbox.cos.COSName
import com.tom_roush.pdfbox.cos.COSNumber
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.common.PDRectangle
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotation
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDAnnotationText
import com.tom_roush.pdfbox.pdmodel.interactive.annotation.PDBorderStyleDictionary
import java.io.File

/**
 * 一个已打开的 PDF：PdfRenderer 负责渲染位图，PdfBox PDDocument 负责注释读写。
 * 标注/留言保存在内存模型中即时叠加显示（PdfRenderer 不渲染注释），保存时写入文档。
 */
class PdfSession(context: Context, val file: File) {

    companion object {
        private val INK_LIST: COSName = COSName.getPDFName("InkList")
    }

    private val pfd: ParcelFileDescriptor =
        ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    private val renderer = PdfRenderer(pfd)
    val doc: PDDocument

    val pageCount: Int
    private val pageW: FloatArray
    private val pageH: FloatArray

    val strokes = mutableMapOf<Int, MutableList<Stroke>>()
    val notes = mutableMapOf<Int, MutableList<NoteMark>>()

    /** 撤销栈：(页码, 类型, 对象)。 */
    private val undoStack = ArrayDeque<Triple<Int, String, Any>>()

    private val renderLock = Any()
    val docLock = Any() // PDDocument 访问锁（搜索线程 / 保存共用）

    init {
        PDFBoxResourceLoader.init(context.applicationContext)
        doc = PDDocument.load(file)
        pageCount = renderer.pageCount
        pageW = FloatArray(pageCount)
        pageH = FloatArray(pageCount)
        for (i in 0 until pageCount) {
            val p = renderer.openPage(i)
            pageW[i] = p.width.toFloat()   // 单位：PDF 点（1/72 英寸）
            pageH[i] = p.height.toFloat()
            p.close()
        }
        importAnnotations()
    }

    fun pageWidth(i: Int) = pageW[i]
    fun pageHeight(i: Int) = pageH[i]

    // ---- 渲染 ----

    fun renderPage(index: Int, widthPx: Int, heightPx: Int): Bitmap {
        synchronized(renderLock) {
            val bmp = Bitmap.createBitmap(
                widthPx.coerceAtLeast(1), heightPx.coerceAtLeast(1), Bitmap.Config.ARGB_8888)
            bmp.eraseColor(Color.WHITE)
            val page = renderer.openPage(index)
            page.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
            page.close()
            return bmp
        }
    }

    // ---- 注释模型 ----

    fun strokesOf(page: Int): List<Stroke> = strokes[page] ?: emptyList()
    fun notesOf(page: Int): List<NoteMark> = notes[page] ?: emptyList()

    fun addStroke(page: Int, stroke: Stroke) {
        strokes.getOrPut(page) { mutableListOf() }.add(stroke)
        undoStack.addLast(Triple(page, "stroke", stroke))
    }

    fun addNote(page: Int, note: NoteMark) {
        notes.getOrPut(page) { mutableListOf() }.add(note)
        undoStack.addLast(Triple(page, "note", note))
    }

    fun removeNote(page: Int, note: NoteMark) {
        notes[page]?.remove(note)
        undoStack.removeAll { it.third === note }
    }

    fun undo(): Boolean {
        val item = undoStack.removeLastOrNull() ?: return false
        when (item.second) {
            "stroke" -> strokes[item.first]?.remove(item.third)
            "note" -> notes[item.first]?.remove(item.third)
        }
        return true
    }

    /** 擦除 (x, y)（PDF 坐标）附近 r 点内的笔画，返回是否有删除。 */
    fun eraseNear(page: Int, x: Float, y: Float, r: Float): Boolean {
        val list = strokes[page] ?: return false
        var removed = false
        val it = list.iterator()
        while (it.hasNext()) {
            val s = it.next()
            var hit = false
            for (i in 1 until s.points.size) {
                val (ax, ay, _) = s.points[i - 1]
                val (bx, by, _) = s.points[i]
                if (segDist(x, y, ax, ay, bx, by) <= r) { hit = true; break }
            }
            if (!hit && s.points.size == 1) {
                val (px, py, _) = s.points[0]
                if (segDist(x, y, px, py, px, py) <= r) hit = true
            }
            if (hit) {
                it.remove()
                undoStack.removeAll { u -> u.third === s }
                removed = true
            }
        }
        return removed
    }

    /** 命中便签（点击点半径 r 点内）。 */
    fun noteAt(page: Int, x: Float, y: Float, r: Float): NoteMark? {
        return notesOf(page).firstOrNull {
            kotlin.math.abs(it.x - x) <= r && kotlin.math.abs(it.y - y) <= r
        }
    }

    // ---- 已有注释导入（PdfRenderer 不渲染注释，导入到模型里显示） ----

    private fun importAnnotations() {
        synchronized(docLock) {
            for (i in 0 until doc.numberOfPages) {
                val page = doc.getPage(i)
                for (annot in page.annotations) {
                    when {
                        annot.subtype == "Ink" -> {
                            val stroke = Stroke(color = annotColor(annot), saved = true)
                            val inkList = annot.cosObject.getItem(INK_LIST) as? COSArray
                                ?: continue
                            for (pathObj in inkList) {
                                val path = pathObj as? COSArray ?: continue
                                var j = 0
                                while (j + 1 < path.size()) {
                                    val x = (path.getObject(j) as? COSNumber)?.floatValue()
                                    val y = (path.getObject(j + 1) as? COSNumber)?.floatValue()
                                    if (x != null && y != null) {
                                        stroke.points.add(Triple(x, y, 0.6f))
                                    }
                                    j += 2
                                }
                            }
                            if (stroke.points.size >= 2) {
                                strokes.getOrPut(i) { mutableListOf() }.add(stroke)
                            }
                        }
                        annot is PDAnnotationText -> {
                            val text = annot.contents ?: continue
                            val r = annot.rectangle ?: continue
                            notes.getOrPut(i) { mutableListOf() }.add(
                                NoteMark((r.lowerLeftX + r.upperRightX) / 2,
                                         (r.lowerLeftY + r.upperRightY) / 2,
                                         text, saved = true))
                        }
                    }
                }
            }
        }
    }

    private fun annotColor(annot: PDAnnotation): Int {
        return runCatching {
            val c = annot.cosObject.getItem(COSName.C) as? COSArray ?: return Color.RED
            if (c.size() >= 3) {
                Color.rgb(
                    (((c.getObject(0) as COSNumber).floatValue()) * 255).toInt(),
                    (((c.getObject(1) as COSNumber).floatValue()) * 255).toInt(),
                    (((c.getObject(2) as COSNumber).floatValue()) * 255).toInt())
            } else Color.RED
        }.getOrDefault(Color.RED)
    }

    // ---- 保存 ----

    /** 把未保存的标注/留言写入 PDDocument 并保存到 out。 */
    fun saveTo(out: File) {
        synchronized(docLock) {
            for ((pageIndex, list) in strokes) {
                val page = doc.getPage(pageIndex)
                for (s in list) {
                    if (s.saved || s.points.isEmpty()) continue
                    // 直接操作页面的 /Annots COS 数组（绕过抽象类 PDAnnotation）
                    val cosPage = page.cosObject
                    val annots = (cosPage.getItem(COSName.ANNOTS) as? COSArray)
                        ?: COSArray().also { cosPage.setItem(COSName.ANNOTS, it) }
                    annots.add(toInkDict(s))
                    s.saved = true
                }
            }
            for ((pageIndex, list) in notes) {
                val page = doc.getPage(pageIndex)
                for (n in list) {
                    if (n.saved) continue
                    page.annotations.add(toTextAnnot(n))
                    n.saved = true
                }
            }
            doc.save(out)
        }
    }

    private fun toInkDict(s: Stroke): COSDictionary {
        // pdfbox-android 未内置 PDAnnotationInk，直接组装 COS 字典
        val dict = COSDictionary()
        dict.setName(COSName.TYPE, "Annot")
        dict.setName(COSName.SUBTYPE, "Ink")
        val path = COSArray()
        for (p in s.points) {
            path.add(COSFloat(p.first))
            path.add(COSFloat(p.second))
        }
        val inkList = COSArray()
        inkList.add(path)
        dict.setItem(INK_LIST, inkList)
        // 包围盒 + 颜色 + 线宽
        val xs = s.points.map { it.first }
        val ys = s.points.map { it.second }
        val pad = s.widthPt + 1f
        dict.setItem(COSName.RECT, PDRectangle(
            xs.min() - pad, ys.min() - pad,
            xs.max() - xs.min() + 2 * pad, ys.max() - ys.min() + 2 * pad).cosObject)
        val colorArr = COSArray()
        colorArr.add(COSFloat(Color.red(s.color) / 255f))
        colorArr.add(COSFloat(Color.green(s.color) / 255f))
        colorArr.add(COSFloat(Color.blue(s.color) / 255f))
        dict.setItem(COSName.C, colorArr)
        val avgP = s.points.map { it.third }.average().toFloat()
        val bs = COSDictionary()
        bs.setFloat(COSName.getPDFName("W"), (s.widthPt * avgP).coerceAtLeast(0.4f))
        dict.setItem(COSName.getPDFName("BS"), bs)
        return dict
    }

    private fun toTextAnnot(n: NoteMark): PDAnnotationText {
        val annot = PDAnnotationText()
        annot.contents = n.text
        annot.rectangle = PDRectangle(n.x - 9, n.y - 9, 18f, 18f)
        return annot
    }

    fun close() {
        runCatching { renderer.close() }
        runCatching { pfd.close() }
        synchronized(docLock) { runCatching { doc.close() } }
    }
}
