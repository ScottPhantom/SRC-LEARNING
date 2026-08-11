from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)


def create_line_icon(
    icon_type: str,
    size: int = 24,
    color: QColor | None = None,
    stroke_width: float = 2.0,
) -> QIcon:
    """Tạo QIcon dạng nét vẽ (line icon) sắc nét ở mọi độ phân giải (High-DPI)."""
    color = QColor("#F5F5F7") if color is None else color
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    pen = QPen(color, stroke_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    rect = QRectF(2.5, 2.5, size - 5.0, size - 5.0)
    center = rect.center()

    if icon_type == "history":
        # Đồng hồ / Lịch sử bài thi
        radius = rect.width() / 2.0 - 1.0
        painter.drawEllipse(center, radius, radius)
        path = QPainterPath()
        path.moveTo(center)
        path.lineTo(center.x(), center.y() - radius * 0.55)
        path.moveTo(center)
        path.lineTo(center.x() + radius * 0.45, center.y())
        painter.drawPath(path)

    elif icon_type == "refresh":
        # Circular arrow: the filled head shares its tip with the arc endpoint,
        # avoiding the detached/skewed arrowhead seen with the old stroked V.
        radius = rect.width() / 2.0 - 1.8
        # Draw clockwise and finish in the upper-right quadrant so the entire
        # arrowhead remains inside the 24 px icon bounds.
        start_angle = 320.0
        span_angle = -280.0
        end_angle = start_angle + span_angle

        arc_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        path = QPainterPath()
        path.arcMoveTo(arc_rect, start_angle)
        path.arcTo(arc_rect, start_angle, span_angle)
        painter.drawPath(path)

        rad = math.radians(end_angle)
        tip = QPointF(
            center.x() + radius * math.cos(rad),
            center.y() - radius * math.sin(rad),
        )
        tangent = QPointF(math.sin(rad), math.cos(rad))
        normal = QPointF(-tangent.y(), tangent.x())
        arrow_length = 4.6
        half_width = 2.65
        base = QPointF(
            tip.x() - tangent.x() * arrow_length,
            tip.y() - tangent.y() * arrow_length,
        )
        wing_1 = QPointF(
            base.x() + normal.x() * half_width,
            base.y() + normal.y() * half_width,
        )
        wing_2 = QPointF(
            base.x() - normal.x() * half_width,
            base.y() - normal.y() * half_width,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF((tip, wing_1, wing_2)))

    elif icon_type == "settings":
        # Bánh răng (Gear) 6 răng với lỗ tròn ở giữa
        r_outer = rect.width() / 2.0 - 0.5
        r_inner = r_outer * 0.68
        r_hole = r_outer * 0.35

        painter.drawEllipse(center, r_hole, r_hole)

        teeth = 6
        path = QPainterPath()
        for i in range(teeth):
            angle1 = (i * 360 / teeth - 14) * math.pi / 180
            angle2 = (i * 360 / teeth + 14) * math.pi / 180

            p_in1 = QPointF(center.x() + r_inner * math.cos(angle1), center.y() + r_inner * math.sin(angle1))
            p_out1 = QPointF(center.x() + r_outer * math.cos(angle1), center.y() + r_outer * math.sin(angle1))
            p_out2 = QPointF(center.x() + r_outer * math.cos(angle2), center.y() + r_outer * math.sin(angle2))
            p_in2 = QPointF(center.x() + r_inner * math.cos(angle2), center.y() + r_inner * math.sin(angle2))

            if i == 0:
                path.moveTo(p_in1)
            else:
                path.lineTo(p_in1)
            path.lineTo(p_out1)
            path.lineTo(p_out2)
            path.lineTo(p_in2)

        path.closeSubpath()
        painter.drawPath(path)

    elif icon_type == "arrow_right":
        # Mũi tên sang phải CTA
        y = center.y()
        left_x = rect.left() + 2.0
        right_x = rect.right() - 2.0
        painter.drawLine(QPointF(left_x, y), QPointF(right_x, y))
        arrow = QPainterPath()
        arrow.moveTo(right_x - 5.5, y - 5.0)
        arrow.lineTo(right_x, y)
        arrow.lineTo(right_x - 5.5, y + 5.0)
        painter.drawPath(arrow)

    elif icon_type == "logo":
        # Icon logo thương hiệu
        path = QPainterPath()
        path.addRoundedRect(rect, 5.0, 5.0)
        painter.drawPath(path)

        r = rect.width() / 2.0 - 1.0
        inner_path = QPainterPath()
        inner_path.moveTo(center.x() - r * 0.5, center.y() + r * 0.2)
        inner_path.cubicTo(
            center.x() - r * 0.2, center.y() - r * 0.6,
            center.x() + r * 0.2, center.y() + r * 0.6,
            center.x() + r * 0.5, center.y() - r * 0.2
        )
        painter.drawPath(inner_path)

    painter.end()
    return QIcon(pixmap)
