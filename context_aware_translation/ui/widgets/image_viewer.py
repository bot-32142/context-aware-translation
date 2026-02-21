"""Zoomable image viewer widget."""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)


class ClickableRectItem(QGraphicsRectItem):
    """A clickable rectangle item that emits a callback when clicked."""

    def __init__(self, rect, index: int, on_click: Callable[[int], None], parent=None):
        """Initialize the clickable rectangle.

        Args:
            rect: QRectF defining the rectangle bounds
            index: Index of this bbox
            on_click: Callback to invoke with index when clicked
            parent: Parent graphics item
        """
        super().__init__(rect, parent)
        self.index = index
        self.on_click = on_click
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)

    def mousePressEvent(self, event):
        """Handle mouse press events.

        Args:
            event: Mouse event
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click(self.index)
            event.accept()
        else:
            super().mousePressEvent(event)


class ImageViewer(QGraphicsView):
    """A zoomable image viewer with pan and zoom capabilities."""

    bbox_clicked = Signal(int)

    def __init__(self, parent=None):
        """Initialize the image viewer.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        # Create scene
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # Pixmap item
        self.pixmap_item: QGraphicsPixmapItem | None = None

        # Bbox overlay items
        self._bbox_rects: list[QGraphicsRectItem] = []

        # Zoom state
        self._zoom_factor = 1.0
        self._zoom_step = 1.1  # 10% per step for smoother zooming

        # Configure view
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)

    def set_image(self, data: bytes) -> None:
        """Load image from binary data.

        Args:
            data: Image binary data
        """
        # Load image from bytes
        image = QImage()
        if not image.loadFromData(data):
            self.clear_image()
            return

        pixmap = QPixmap.fromImage(image)
        self._set_pixmap(pixmap)

    def _set_pixmap(self, pixmap: QPixmap) -> None:
        """Set the pixmap in the scene.

        Args:
            pixmap: QPixmap to display
        """
        # Clear bboxes before removing pixmap
        self.clear_bboxes()

        # Clear existing item
        if self.pixmap_item:
            self._scene.removeItem(self.pixmap_item)

        # Add new item
        self.pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self.pixmap_item.boundingRect())

        # Reset zoom and fit to window
        self.reset_zoom()
        self.fit_to_window()

    def zoom_in(self) -> None:
        """Zoom in by the zoom step factor."""
        self._zoom(self._zoom_step)

    def zoom_out(self) -> None:
        """Zoom out by the zoom step factor."""
        self._zoom(1.0 / self._zoom_step)

    def _zoom(self, factor: float) -> None:
        """Apply zoom factor.

        Args:
            factor: Zoom factor to apply
        """
        target_zoom = self._zoom_factor * factor
        # Clamp zoom factor to reasonable bounds (0.05x to 50x)
        clamped_zoom = max(0.05, min(50.0, target_zoom))
        effective_factor = clamped_zoom / self._zoom_factor
        if effective_factor != 1.0:
            self.scale(effective_factor, effective_factor)
        self._zoom_factor = clamped_zoom

    def fit_to_window(self) -> None:
        """Fit the image to the view window."""
        if self.pixmap_item:
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            # Update zoom factor based on current transform
            self._zoom_factor = self.transform().m11()

    def reset_zoom(self) -> None:
        """Reset zoom to 100%."""
        self.resetTransform()
        self._zoom_factor = 1.0

    def set_bboxes(self, bboxes: list[object]) -> None:
        """Set bounding boxes to overlay on the image.

        Args:
            bboxes: List of objects with x, y, width, height attributes (normalized 0.0-1.0)
        """
        # Clear existing bboxes
        self.clear_bboxes()

        # Can't add bboxes without a pixmap
        if self.pixmap_item is None:
            return

        # Get pixmap dimensions
        pixmap_size = self.pixmap_item.pixmap().size()
        pixmap_w = pixmap_size.width()
        pixmap_h = pixmap_size.height()

        # Create rectangle items for each bbox
        for index, bbox in enumerate(bboxes):
            # Convert normalized coordinates to pixel coordinates
            px = bbox.x * pixmap_w
            py = bbox.y * pixmap_h
            pw = bbox.width * pixmap_w
            ph = bbox.height * pixmap_h

            # Create clickable rect item
            from PySide6.QtCore import QRectF

            rect_item = ClickableRectItem(
                QRectF(px, py, pw, ph),
                index,
                lambda idx=index: self.bbox_clicked.emit(idx),
            )

            # Style: blue pen (2px), semi-transparent blue fill (40% opacity)
            pen = QPen(QColor(0, 120, 255), 2)
            brush = QBrush(QColor(0, 120, 255, int(255 * 0.4)))
            rect_item.setPen(pen)
            rect_item.setBrush(brush)

            # Set Z-value above pixmap
            rect_item.setZValue(1)

            # Add to scene and store
            self._scene.addItem(rect_item)
            self._bbox_rects.append(rect_item)

    def highlight_bbox(self, index: int) -> None:
        """Highlight a specific bbox or clear all highlights.

        Args:
            index: Index of bbox to highlight, or -1 to clear all highlights
        """
        # Default style: thin blue border, semi-transparent blue fill
        default_pen = QPen(QColor(0, 120, 255), 2)
        default_brush = QBrush(QColor(0, 120, 255, int(255 * 0.4)))

        # Highlighted style: thick orange border, semi-transparent orange fill
        highlight_pen = QPen(QColor(255, 140, 0), 3)
        highlight_brush = QBrush(QColor(255, 140, 0, int(255 * 0.3)))

        # Reset all to default style
        for rect in self._bbox_rects:
            rect.setPen(default_pen)
            rect.setBrush(default_brush)

        # Highlight specific bbox if valid index
        if 0 <= index < len(self._bbox_rects):
            self._bbox_rects[index].setPen(highlight_pen)
            self._bbox_rects[index].setBrush(highlight_brush)

    def clear_bboxes(self) -> None:
        """Clear all bbox overlay rectangles."""
        for rect in self._bbox_rects:
            self._scene.removeItem(rect)
        self._bbox_rects.clear()

    def clear_image(self) -> None:
        """Clear the current image and overlays."""
        self.clear_bboxes()
        if self.pixmap_item is not None:
            self._scene.removeItem(self.pixmap_item)
            self.pixmap_item = None
        self._scene.setSceneRect(0, 0, 0, 0)
        self.reset_zoom()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel events for zooming.

        Args:
            event: Wheel event
        """
        # Zoom on wheel (we have scroll hand drag for panning)
        if event.angleDelta().y() > 0:
            self.zoom_in()
        elif event.angleDelta().y() < 0:
            self.zoom_out()
        event.accept()
