package com.smallh.pdfreader

import android.graphics.Color
import android.graphics.RectF
import com.tom_roush.pdfbox.cos.COSDictionary

/** 当前工具。 */
enum class Tool { SELECT, PEN, NOTE, ERASER, SELECT_STROKE }

/** 一笔手写：PDF 页面坐标（点，1/72 英寸，原点在左下），带压感。 */
data class Stroke(
    val points: MutableList<Triple<Float, Float, Float>> = mutableListOf(), // x, y, pressure
    var color: Int = Color.RED,
    val widthPt: Float = 3f,
    var saved: Boolean = false, // 已写入 PDDocument，重复保存时跳过
    var inkDict: COSDictionary? = null, // 已写入文档的注释字典（变换/删除时用于移除旧注释）
)

/** 留言便签：位置为便签图标中心（PDF 坐标）。 */
data class NoteMark(
    val x: Float,
    val y: Float,
    var text: String,
    var saved: Boolean = false,
    var noteDict: COSDictionary? = null,
)

/** 一条搜索命中：rect 为 PDF 页面坐标。 */
data class SearchHit(
    val page: Int,
    val rect: RectF,
    val snippet: String,
)

/** 点到线段距离（橡皮擦命中判定用）。 */
fun segDist(px: Float, py: Float, ax: Float, ay: Float, bx: Float, by: Float): Float {
    val dx = bx - ax
    val dy = by - ay
    if (dx == 0f && dy == 0f) {
        val ddx = px - ax
        val ddy = py - ay
        return kotlin.math.sqrt(ddx * ddx + ddy * ddy)
    }
    var t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = t.coerceIn(0f, 1f)
    val cx = ax + t * dx
    val cy = ay + t * dy
    val ddx = px - cx
    val ddy = py - cy
    return kotlin.math.sqrt(ddx * ddx + ddy * ddy)
}

/** 射线法判断点是否在多边形内（圈选命中判定）。poly 为 (x, y) 列表。 */
fun pointInPolygon(x: Float, y: Float, poly: List<Pair<Float, Float>>): Boolean {
    var inside = false
    var j = poly.size - 1
    for (i in poly.indices) {
        val (xi, yi) = poly[i]
        val (xj, yj) = poly[j]
        if ((yi > y) != (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) {
            inside = !inside
        }
        j = i
    }
    return inside
}
