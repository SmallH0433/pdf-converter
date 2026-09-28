package com.smallh.pdfreader

import android.graphics.RectF
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.text.PDFTextStripper
import com.tom_roush.pdfbox.text.TextPosition

/**
 * 全文查找：逐页用 PDFTextStripper 提取文本与字形位置，收集命中矩形与摘录。
 * 只支持文字层搜索（安卓版暂无 OCR）。
 */
class PdfSearcher(private val doc: PDDocument, private val docLock: Any) {

    fun search(needle: String, onProgress: (done: Int, total: Int) -> Unit,
               isCancelled: () -> Boolean): List<SearchHit> {
        val hits = mutableListOf<SearchHit>()
        val stripper = LocatorStripper(needle)
        val total = doc.numberOfPages
        synchronized(docLock) {
            for (i in 0 until total) {
                if (isCancelled()) break
                stripper.pageIndex = i
                stripper.startPage = i + 1
                stripper.endPage = i + 1
                stripper.getText(doc) // 触发 writeString 回调收集命中
                onProgress(i + 1, total)
            }
        }
        return stripper.hits
    }

    private class LocatorStripper(needle: String) : PDFTextStripper() {
        private val low = needle.lowercase().replace(" ", "")
        val hits = mutableListOf<SearchHit>()
        var pageIndex = 0

        override fun writeString(text: String, textPositions: MutableList<TextPosition>) {
            val lowText = text.lowercase()
            var idx = lowText.indexOf(low)
            while (idx >= 0) {
                val end = (idx + low.length).coerceAtMost(textPositions.size)
                if (idx < end) {
                    val rect = unionRect(textPositions.subList(idx, end))
                    if (rect != null) {
                        val snippet = text.replace('\n', ' ')
                            .substring(0, text.length.coerceAtMost(80))
                        hits.add(SearchHit(pageIndex, rect, snippet))
                    }
                }
                idx = lowText.indexOf(low, idx + 1)
            }
            super.writeString(text, textPositions)
        }

        private fun unionRect(positions: List<TextPosition>): RectF? {
            var l = Float.MAX_VALUE
            var t = Float.MAX_VALUE
            var r = -Float.MAX_VALUE
            var b = -Float.MAX_VALUE
            for (tp in positions) {
                // 未旋转页面：xDirAdj/yDirAdj 即页面坐标（y 向下），heightDir 为字高
                val x = tp.xDirAdj
                val yTop = tp.yDirAdj - tp.heightDir
                l = minOf(l, x)
                t = minOf(t, yTop)
                r = maxOf(r, x + tp.widthDirAdj)
                b = maxOf(b, yTop + tp.heightDir)
            }
            if (l > r || t > b) return null
            // 转为 y 向上的 PDF 用户坐标：PDFTextStripper 的 y 是从页面顶部向下
            return RectF(l, t, r, b) // 保持 top-down，由 PageView 翻转
        }
    }
}
