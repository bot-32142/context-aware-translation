"""Collapsible section widget with animated expand/collapse."""

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A collapsible section with header and animated content area."""

    toggled = Signal(bool)

    def __init__(self, title: str = "", parent=None):
        """Initialize the collapsible section.

        Args:
            title: Section title text
            parent: Parent widget
        """
        super().__init__(parent)

        self._is_expanded = False
        self._animation_duration = 200

        # Create toggle button (header)
        self.toggle_button = QToolButton()
        self.toggle_button.setStyleSheet("QToolButton { border: none; }")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        self.toggle_button.clicked.connect(self._on_toggle)

        # Create content area (QScrollArea used for maximumHeight animation only)
        self.content_area = QScrollArea()
        self.content_area.setMaximumHeight(0)
        self.content_area.setMinimumHeight(0)
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.content_area.setFrameShape(QFrame.Shape.NoFrame)
        self.content_area.setWidgetResizable(True)
        self.content_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Create layout
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content_area)

        # Animation
        self.toggle_animation = QParallelAnimationGroup(self)

        self.content_animation = QPropertyAnimation(self.content_area, b"maximumHeight")
        self.content_animation.setDuration(self._animation_duration)
        self.content_animation.setEasingCurve(QEasingCurve.Type.InOutQuart)
        self.toggle_animation.addAnimation(self.content_animation)

        self.min_animation = QPropertyAnimation(self.content_area, b"minimumHeight")
        self.min_animation.setDuration(self._animation_duration)
        self.min_animation.setEasingCurve(QEasingCurve.Type.InOutQuart)
        self.toggle_animation.addAnimation(self.min_animation)

    def set_content(self, widget: QWidget) -> None:
        """Set the collapsible content widget.

        Args:
            widget: Widget to display in the content area
        """
        self.content_area.setWidget(widget)

        # Update animation end value based on content size
        if self._is_expanded:
            self.refresh_content_height()

    def refresh_content_height(self) -> None:
        """Refresh content height for dynamic widgets after they change size."""
        if not self._is_expanded:
            return
        content_widget = self.content_area.widget()
        if content_widget is None:
            self.content_area.setMinimumHeight(0)
            self.content_area.setMaximumHeight(0)
            return
        content_widget.adjustSize()
        content_height = max(content_widget.sizeHint().height(), content_widget.minimumSizeHint().height())
        self.content_area.setMinimumHeight(content_height)
        self.content_area.setMaximumHeight(content_height)

    def set_expanded(self, expanded: bool) -> None:
        """Programmatically expand or collapse the section.

        Args:
            expanded: Whether section should be expanded
        """
        if expanded == self._is_expanded:
            return

        self.toggle_button.setChecked(expanded)
        self._animate_toggle()

    def is_expanded(self) -> bool:
        """Check if section is expanded.

        Returns:
            True if expanded, False if collapsed
        """
        return self._is_expanded

    def _on_toggle(self) -> None:
        """Handle toggle button click."""
        self._animate_toggle()

    def _animate_toggle(self) -> None:
        """Animate the expand/collapse transition."""
        checked = self.toggle_button.isChecked()
        arrow_type = Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        self.toggle_button.setArrowType(arrow_type)

        # Calculate content height
        content_widget = self.content_area.widget()
        if content_widget is not None:
            content_widget.adjustSize()
        content_height = (
            max(content_widget.sizeHint().height(), content_widget.minimumSizeHint().height())
            if content_widget
            else 0
        )

        # Set animation start and end values
        if checked:
            # Expanding
            self.content_animation.setStartValue(0)
            self.content_animation.setEndValue(content_height)
            self.min_animation.setStartValue(0)
            self.min_animation.setEndValue(content_height)
        else:
            # Collapsing
            self.content_animation.setStartValue(content_height)
            self.content_animation.setEndValue(0)
            self.min_animation.setStartValue(content_height)
            self.min_animation.setEndValue(0)

        # Start animation
        self.toggle_animation.start()

        # Update state
        self._is_expanded = checked
        self.toggled.emit(checked)
