import gi
import subprocess
import os
import io
import cairo
from dataclasses import dataclass
from enum import Enum, auto
from datetime import datetime

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, Pango, PangoCairo

from clipshot.config import Config


PRESET_COLORS = [
    ("Red",    (1.0, 0.0, 0.0)),
    ("Green",  (0.0, 0.75, 0.0)),
    ("Blue",   (0.2, 0.4, 1.0)),
    ("Yellow", (1.0, 0.9, 0.0)),
    ("Orange", (1.0, 0.5, 0.0)),
    ("Purple", (0.6, 0.0, 1.0)),
    ("Pink",   (1.0, 0.4, 0.7)),
    ("Black",  (0.0, 0.0, 0.0)),
    ("White",  (1.0, 1.0, 1.0)),
    ("Cyan",   (0.0, 0.8, 0.8)),
]

HANDLE_SIZE = 6  # Selection handle square size


class ToolMode(Enum):
    NONE = auto()
    REDACT = auto()
    RECT = auto()


@dataclass
class RectAnnotation:
    x: float
    y: float
    width: float
    height: float
    color: tuple
    thickness: float = 2.0
    filled: bool = False


@dataclass
class TextAnnotation:
    x: float
    y: float
    text: str
    font_family: str = "Sans"
    font_size: float = 20.0
    color: tuple = (1.0, 0.0, 0.0)


class AnnotationWindow(Gtk.Window):
    def __init__(self, app, config, pixbuf, screenshot_path):
        super().__init__(application=app)
        self._config = config
        self._pixbuf = pixbuf
        self._screenshot_path = screenshot_path

        self._annotations = []
        self._selected = None  # Currently selected annotation (reference)
        self._tool = ToolMode.NONE
        self._color = PRESET_COLORS[0][1]
        self._rect_thickness = 2.0
        self._zoom = 1.0

        # Drag state
        self._drag_creating = False
        self._drag_moving = False
        self._drag_annotation = None
        self._drag_offset = (0, 0)
        self._create_start = None
        self._create_current = None
        self._drag_started = False  # True if mouse moved significantly

        # Resize state
        self._drag_resizing = False
        self._resize_fixed_corner = None  # (x, y) of the corner opposite the handle

        self._setup_ui()

    def _setup_ui(self):
        self.set_title("Clipshot — Annotate")
        pw, ph = self._pixbuf.get_width(), self._pixbuf.get_height()
        self.set_default_size(min(pw + 40, 1200), min(ph + 120, 800))

        # Header bar
        header = Gtk.HeaderBar()
        self.set_titlebar(header)

        for label, handler in [
            ("Save", self._action_save),
            ("Save + Copy Path", self._action_save_copy_path),
            ("Save + Copy Image", self._action_save_copy_image),
            ("Copy Image", self._action_copy_image),
        ]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda b, h=handler: h())
            header.pack_start(btn)

        # Main layout
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(vbox)

        toolbar = self._build_toolbar()
        vbox.append(toolbar)
        vbox.append(Gtk.Separator())

        # Canvas in ScrolledWindow
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_vexpand(True)
        self._scrolled.set_hexpand(True)
        vbox.append(self._scrolled)

        self._canvas = Gtk.DrawingArea()
        self._canvas.set_draw_func(self._on_draw)
        self._update_canvas_size()
        self._scrolled.set_child(self._canvas)

        # Drag gesture
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self._canvas.add_controller(drag)

        # Ctrl+Scroll zoom
        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll.connect("scroll", self._on_scroll)
        self._canvas.add_controller(scroll)

        # Keyboard
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctrl)

        self.present()

    # ── Toolbar ──────────────────────────────────────────────

    def _build_toolbar(self):
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        # Redact toggle
        self._redact_btn = Gtk.ToggleButton(label="Redact")
        self._redact_btn.connect("toggled", self._on_tool_toggled, ToolMode.REDACT)
        toolbar.append(self._redact_btn)

        # Rect toggle + settings button
        rect_box = Gtk.Box(spacing=0)
        self._rect_btn = Gtk.ToggleButton(label="Rect")
        self._rect_btn.connect("toggled", self._on_tool_toggled, ToolMode.RECT)
        rect_box.append(self._rect_btn)

        rect_settings = Gtk.MenuButton()
        rect_settings.set_icon_name("document-properties-symbolic")
        rect_settings.add_css_class("flat")

        rect_popover = Gtk.Popover()
        rbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("start", "end", "top", "bottom"):
            getattr(rbox, f"set_margin_{side}")(8)
        rbox.append(Gtk.Label(label="Line Thickness"))
        self._thickness_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1, 10, 0.5
        )
        self._thickness_scale.set_value(2)
        self._thickness_scale.set_size_request(150, -1)
        self._thickness_scale.connect(
            "value-changed", self._on_thickness_changed,
        )
        rbox.append(self._thickness_scale)
        rect_popover.set_child(rbox)
        rect_settings.set_popover(rect_popover)
        rect_box.append(rect_settings)
        toolbar.append(rect_box)

        # Text button
        self._text_btn = Gtk.Button(label="Text")
        self._text_btn.connect("clicked", self._on_text_clicked)
        toolbar.append(self._text_btn)

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Color picker — drawn swatches
        self._color_indicator = Gtk.DrawingArea()
        self._color_indicator.set_content_width(22)
        self._color_indicator.set_content_height(22)
        self._color_indicator.set_draw_func(self._draw_color_indicator)

        self._color_btn = Gtk.MenuButton()
        self._color_btn.set_child(self._color_indicator)
        self._color_btn.set_popover(self._build_color_popover())
        self._color_btn.set_tooltip_text("Color")
        toolbar.append(self._color_btn)

        # Undo
        undo_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        undo_btn.set_tooltip_text("Undo (Ctrl+Z)")
        undo_btn.connect("clicked", lambda b: self._undo())
        toolbar.append(undo_btn)

        return toolbar

    def _draw_color_indicator(self, area, cr, w, h):
        r, g, b = self._color
        cr.set_source_rgb(r, g, b)
        cr.rectangle(1, 1, w - 2, h - 2)
        cr.fill()
        # Border
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.stroke()

    def _build_color_popover(self):
        popover = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("start", "end", "top", "bottom"):
            getattr(vbox, f"set_margin_{side}")(6)

        grid = Gtk.Grid()
        grid.set_row_spacing(4)
        grid.set_column_spacing(4)

        for i, (name, color) in enumerate(PRESET_COLORS):
            btn = Gtk.Button()
            btn.set_tooltip_text(name)
            swatch = Gtk.DrawingArea()
            swatch.set_content_width(24)
            swatch.set_content_height(24)
            r, g, b = color
            swatch.set_draw_func(
                lambda a, cr, w, h, r=r, g=g, b=b: (
                    cr.set_source_rgb(r, g, b),
                    cr.rectangle(0, 0, w, h),
                    cr.fill(),
                )
            )
            btn.set_child(swatch)
            btn.connect("clicked", lambda b, c=color: self._pick_color(c, popover))
            grid.attach(btn, i % 5, i // 5, 1, 1)

        vbox.append(grid)

        # Custom color picker button
        custom_btn = Gtk.Button(label="Custom…")
        custom_btn.connect("clicked", lambda b: self._open_color_dialog(popover))
        vbox.append(custom_btn)

        popover.set_child(vbox)
        return popover

    def _open_color_dialog(self, popover):
        popover.popdown()
        dialog = Gtk.ColorDialog()
        dialog.set_title("Pick a Color")
        initial = Gdk.RGBA()
        initial.red, initial.green, initial.blue, initial.alpha = (*self._color, 1.0)
        dialog.choose_rgba(self, initial, None, self._on_color_dialog_done)

    def _on_color_dialog_done(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
            color = (rgba.red, rgba.green, rgba.blue)
            self._color = color
            if self._selected:
                self._selected.color = color
                self._canvas.queue_draw()
            self._color_indicator.queue_draw()
        except GLib.Error:
            pass  # User cancelled

    def _pick_color(self, color, popover):
        self._color = color
        # Update selected annotation if any
        if self._selected:
            self._selected.color = color
            self._canvas.queue_draw()
        self._color_indicator.queue_draw()
        popover.popdown()

    def _on_thickness_changed(self, scale):
        self._rect_thickness = scale.get_value()
        # Update selected annotation if it's a non-filled rect
        if isinstance(self._selected, RectAnnotation) and not self._selected.filled:
            self._selected.thickness = self._rect_thickness
            self._canvas.queue_draw()

    def _on_tool_toggled(self, btn, mode):
        if btn.get_active():
            # Deactivate the other toggle
            other = (
                self._rect_btn if mode == ToolMode.REDACT else self._redact_btn
            )
            if other.get_active():
                other.set_active(False)
            self._tool = mode
            self._select(None)
        else:
            if self._tool == mode:
                self._tool = ToolMode.NONE

    def _on_text_clicked(self, btn):
        # Deactivate drawing tools
        self._redact_btn.set_active(False)
        self._rect_btn.set_active(False)
        self._tool = ToolMode.NONE

        # If a text annotation is selected, edit it
        editing = isinstance(self._selected, TextAnnotation)
        edit_ann = self._selected if editing else None

        popover = Gtk.Popover()
        popover.set_parent(btn)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{side}")(12)

        box.append(Gtk.Label(label="Text", xalign=0))
        text_entry = Gtk.Entry()
        text_entry.set_placeholder_text("Type here…")
        if editing:
            text_entry.set_text(edit_ann.text)
        box.append(text_entry)

        box.append(Gtk.Label(label="Font", xalign=0))
        fonts = self._get_font_families()
        font_dropdown = Gtk.DropDown.new_from_strings(fonts)
        font_dropdown.set_enable_search(True)
        if editing and edit_ann.font_family in fonts:
            font_dropdown.set_selected(fonts.index(edit_ann.font_family))
        else:
            font_dropdown.set_selected(0)
        box.append(font_dropdown)

        box.append(Gtk.Label(label="Size", xalign=0))
        size_spin = Gtk.SpinButton.new_with_range(8, 120, 1)
        size_spin.set_value(edit_ann.font_size if editing else 20)
        box.append(size_spin)

        done_btn = Gtk.Button(label="Done")
        done_btn.add_css_class("suggested-action")

        def on_done(_widget):
            text = text_entry.get_text().strip()
            if not text:
                popover.popdown()
                return
            selected_idx = font_dropdown.get_selected()
            model = font_dropdown.get_model()
            font = model.get_string(selected_idx) if model else "Sans"
            size = size_spin.get_value()

            if editing:
                edit_ann.text = text
                edit_ann.font_family = font
                edit_ann.font_size = size
                edit_ann.color = self._color
            else:
                # Place at center of visible canvas area
                hadj = self._scrolled.get_hadjustment()
                vadj = self._scrolled.get_vadjustment()
                cx = (hadj.get_value() + hadj.get_page_size() / 2) / self._zoom
                cy = (vadj.get_value() + vadj.get_page_size() / 2) / self._zoom
                ann = TextAnnotation(
                    x=cx, y=cy, text=text,
                    font_family=font, font_size=size,
                    color=self._color,
                )
                self._annotations.append(ann)
                self._select(ann)

            self._canvas.queue_draw()
            popover.popdown()

        done_btn.connect("clicked", on_done)
        text_entry.connect("activate", on_done)
        box.append(done_btn)

        popover.set_child(box)
        popover.popup()

    def _get_font_families(self):
        context = self._canvas.get_pango_context()
        families = context.list_families()
        names = sorted(set(f.get_name() for f in families))
        preferred = ["Sans", "Serif", "Monospace"]
        result = [p for p in preferred if p in names]
        result += [n for n in names if n not in preferred]
        return result

    # ── Selection ────────────────────────────────────────────

    def _select(self, ann):
        """Select an annotation (or None to deselect)."""
        self._selected = ann
        if ann:
            # Sync toolbar to selected annotation's properties
            self._color = ann.color
            self._color_indicator.queue_draw()
            if isinstance(ann, RectAnnotation) and not ann.filled:
                self._rect_thickness = ann.thickness
                self._thickness_scale.set_value(ann.thickness)
        self._canvas.queue_draw()

    # ── Canvas ───────────────────────────────────────────────

    def _update_canvas_size(self):
        w = int(self._pixbuf.get_width() * self._zoom)
        h = int(self._pixbuf.get_height() * self._zoom)
        self._canvas.set_content_width(w)
        self._canvas.set_content_height(h)

    def _on_scroll(self, controller, dx, dy):
        state = controller.get_current_event_state()
        if not (state & Gdk.ModifierType.CONTROL_MASK):
            return False
        old = self._zoom
        factor = 1.15 if dy < 0 else 1 / 1.15
        self._zoom = max(0.1, min(5.0, self._zoom * factor))
        if old != self._zoom:
            self._update_canvas_size()
            self._canvas.queue_draw()
        return True

    def _on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if self._selected:
                self._select(None)
                return True
            self._cleanup_and_close()
            return True
        if keyval == Gdk.KEY_z and (state & Gdk.ModifierType.CONTROL_MASK):
            self._undo()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if self._selected and self._selected in self._annotations:
                self._annotations.remove(self._selected)
                self._select(None)
            return True
        return False

    def _undo(self):
        if self._annotations:
            removed = self._annotations.pop()
            if self._selected is removed:
                self._selected = None
            self._canvas.queue_draw()

    # ── Drawing ──────────────────────────────────────────────

    def _on_draw(self, area, cr, width, height):
        if not self._pixbuf:
            return

        cr.save()
        cr.scale(self._zoom, self._zoom)

        # Screenshot
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()

        # Annotations
        for ann in self._annotations:
            self._draw_annotation(cr, ann)

        # Selection indicator
        if self._selected and self._selected in self._annotations:
            self._draw_selection(cr, self._selected)

        # In-progress creation preview
        if self._drag_creating and self._create_start and self._create_current:
            x1, y1 = self._create_start
            x2, y2 = self._create_current
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            if w > 0 and h > 0:
                self._draw_annotation(
                    cr,
                    RectAnnotation(
                        x=x, y=y, width=w, height=h,
                        color=self._color,
                        thickness=self._rect_thickness,
                        filled=(self._tool == ToolMode.REDACT),
                    ),
                )

        cr.restore()

    def _draw_annotation(self, cr, ann):
        if isinstance(ann, RectAnnotation):
            r, g, b = ann.color
            if ann.filled:
                cr.set_source_rgba(r, g, b, 1.0)
                cr.rectangle(ann.x, ann.y, ann.width, ann.height)
                cr.fill()
            else:
                cr.set_source_rgba(r, g, b, 1.0)
                cr.set_line_width(ann.thickness)
                cr.rectangle(ann.x, ann.y, ann.width, ann.height)
                cr.stroke()

        elif isinstance(ann, TextAnnotation):
            r, g, b = ann.color
            cr.set_source_rgba(r, g, b, 1.0)
            layout = PangoCairo.create_layout(cr)
            font_desc = Pango.FontDescription.from_string(
                f"{ann.font_family} {ann.font_size}"
            )
            layout.set_font_description(font_desc)
            layout.set_text(ann.text, -1)
            cr.move_to(ann.x, ann.y)
            PangoCairo.show_layout(cr, layout)

    def _draw_selection(self, cr, ann):
        """Draw selection handles around an annotation."""
        bounds = self._get_bounds(ann)
        if not bounds:
            return
        bx, by, bw, bh = bounds
        hs = HANDLE_SIZE / self._zoom  # Handle size in image coords

        # Dashed outline
        cr.save()
        cr.set_source_rgba(0.2, 0.5, 1.0, 0.8)
        cr.set_line_width(1.5 / self._zoom)
        cr.set_dash([4 / self._zoom, 3 / self._zoom])
        cr.rectangle(bx - 2 / self._zoom, by - 2 / self._zoom,
                     bw + 4 / self._zoom, bh + 4 / self._zoom)
        cr.stroke()
        cr.set_dash([])

        # Corner + edge midpoint handles (only for rects)
        cr.set_source_rgba(0.2, 0.5, 1.0, 1.0)
        handle_points = [
            (bx, by), (bx + bw, by),
            (bx, by + bh), (bx + bw, by + bh),
        ]
        if isinstance(ann, RectAnnotation):
            handle_points += [
                (bx + bw / 2, by),          # Top mid
                (bx + bw, by + bh / 2),     # Right mid
                (bx + bw / 2, by + bh),     # Bottom mid
                (bx, by + bh / 2),           # Left mid
            ]
        for hx, hy in handle_points:
            cr.rectangle(hx - hs / 2, hy - hs / 2, hs, hs)
            cr.fill()
        cr.restore()

    def _get_bounds(self, ann):
        """Get bounding box of an annotation in image coords."""
        if isinstance(ann, RectAnnotation):
            return (ann.x, ann.y, ann.width, ann.height)
        elif isinstance(ann, TextAnnotation):
            return self._get_text_bounds(ann)
        return None

    # ── Hit testing & dragging ───────────────────────────────

    def _handle_hit_test(self, x, y):
        """Check if (x, y) hits a resize handle of the selected RectAnnotation.
        Returns the fixed corner (opposite) or None."""
        if not isinstance(self._selected, RectAnnotation):
            return None
        ann = self._selected
        hs = (HANDLE_SIZE + 4) / self._zoom  # Generous hit area
        corners = [
            ((ann.x, ann.y), (ann.x + ann.width, ann.y + ann.height)),              # TL → BR fixed
            ((ann.x + ann.width, ann.y), (ann.x, ann.y + ann.height)),              # TR → BL fixed
            ((ann.x, ann.y + ann.height), (ann.x + ann.width, ann.y)),              # BL → TR fixed
            ((ann.x + ann.width, ann.y + ann.height), (ann.x, ann.y)),              # BR → TL fixed
            ((ann.x + ann.width / 2, ann.y), "top"),                                 # Top edge
            ((ann.x + ann.width, ann.y + ann.height / 2), "right"),                  # Right edge
            ((ann.x + ann.width / 2, ann.y + ann.height), "bottom"),                 # Bottom edge
            ((ann.x, ann.y + ann.height / 2), "left"),                               # Left edge
        ]
        for handle_pos, fixed in corners:
            hx, hy = handle_pos
            if abs(x - hx) <= hs and abs(y - hy) <= hs:
                if isinstance(fixed, str):
                    # Edge resize — store edge name
                    return fixed
                return fixed
        return None

    def _hit_test(self, x, y):
        """Find topmost annotation under (x, y) in image coords."""
        for i in range(len(self._annotations) - 1, -1, -1):
            ann = self._annotations[i]
            if isinstance(ann, RectAnnotation):
                if (ann.x <= x <= ann.x + ann.width
                        and ann.y <= y <= ann.y + ann.height):
                    return ann, i
            elif isinstance(ann, TextAnnotation):
                bounds = self._get_text_bounds(ann)
                if bounds:
                    tx, ty, tw, th = bounds
                    if tx <= x <= tx + tw and ty <= y <= ty + th:
                        return ann, i
        return None, -1

    def _get_text_bounds(self, ann):
        context = self._canvas.get_pango_context()
        layout = Pango.Layout.new(context)
        font_desc = Pango.FontDescription.from_string(
            f"{ann.font_family} {ann.font_size}"
        )
        layout.set_font_description(font_desc)
        layout.set_text(ann.text, -1)
        _, logical = layout.get_pixel_extents()
        return (ann.x, ann.y, logical.width, logical.height)

    def _on_drag_begin(self, gesture, start_x, start_y):
        self._drag_started = False
        ix, iy = start_x / self._zoom, start_y / self._zoom

        # Check resize handles on selected annotation first
        fixed = self._handle_hit_test(ix, iy)
        if fixed is not None:
            ann = self._selected
            self._drag_resizing = True
            self._drag_annotation = ann
            if isinstance(fixed, str):
                # Edge resize — compute the fixed edge
                if fixed == "top":
                    self._resize_fixed_corner = (None, ann.y + ann.height)
                elif fixed == "bottom":
                    self._resize_fixed_corner = (None, ann.y)
                elif fixed == "left":
                    self._resize_fixed_corner = (ann.x + ann.width, None)
                elif fixed == "right":
                    self._resize_fixed_corner = (ann.x, None)
            else:
                self._resize_fixed_corner = fixed
            return

        # Check if clicking on an existing annotation
        ann, idx = self._hit_test(ix, iy)
        if ann:
            self._drag_moving = True
            self._drag_annotation = ann
            self._drag_offset = (ix - ann.x, iy - ann.y)
            self._select(ann)
            # Bring to top
            self._annotations.remove(ann)
            self._annotations.append(ann)
            return

        # Create new if tool active
        if self._tool in (ToolMode.REDACT, ToolMode.RECT):
            self._drag_creating = True
            self._create_start = (ix, iy)
            self._create_current = (ix, iy)
            self._select(None)
        else:
            # Clicked empty space with no tool — deselect
            self._select(None)

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if abs(offset_x) > 3 or abs(offset_y) > 3:
            self._drag_started = True

        if self._drag_resizing and self._drag_annotation:
            ok, sx, sy = gesture.get_start_point()
            if ok:
                drag_x = (sx + offset_x) / self._zoom
                drag_y = (sy + offset_y) / self._zoom
                ann = self._drag_annotation
                fx, fy = self._resize_fixed_corner

                if fx is None:
                    # Horizontal edge resize — only change y
                    ann.y = min(drag_y, fy)
                    ann.height = abs(drag_y - fy)
                elif fy is None:
                    # Vertical edge resize — only change x
                    ann.x = min(drag_x, fx)
                    ann.width = abs(drag_x - fx)
                else:
                    # Corner resize — change both
                    ann.x = min(drag_x, fx)
                    ann.y = min(drag_y, fy)
                    ann.width = abs(drag_x - fx)
                    ann.height = abs(drag_y - fy)

                self._canvas.queue_draw()

        elif self._drag_moving and self._drag_annotation and self._drag_started:
            ok, sx, sy = gesture.get_start_point()
            if ok:
                cx = (sx + offset_x) / self._zoom
                cy = (sy + offset_y) / self._zoom
                ox, oy = self._drag_offset
                self._drag_annotation.x = cx - ox
                self._drag_annotation.y = cy - oy
                self._canvas.queue_draw()

        elif self._drag_creating and self._create_start:
            ok, sx, sy = gesture.get_start_point()
            if ok:
                self._create_current = (
                    (sx + offset_x) / self._zoom,
                    (sy + offset_y) / self._zoom,
                )
                self._canvas.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        if self._drag_creating and self._create_start and self._create_current:
            x1, y1 = self._create_start
            x2, y2 = self._create_current
            x, y = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            if w > 2 and h > 2:
                ann = RectAnnotation(
                    x=x, y=y, width=w, height=h,
                    color=self._color,
                    thickness=self._rect_thickness,
                    filled=(self._tool == ToolMode.REDACT),
                )
                self._annotations.append(ann)
                self._select(ann)

        self._drag_creating = False
        self._drag_moving = False
        self._drag_resizing = False
        self._drag_annotation = None
        self._resize_fixed_corner = None
        self._create_start = None
        self._create_current = None
        self._canvas.queue_draw()

    # ── Rendering for export ─────────────────────────────────

    def _render_surface(self):
        w, h = self._pixbuf.get_width(), self._pixbuf.get_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        for ann in self._annotations:
            self._draw_annotation(cr, ann)
        return surface

    def _render_png_bytes(self):
        surface = self._render_surface()
        buf = io.BytesIO()
        surface.write_to_png(buf)
        return buf.getvalue()

    def _generate_filepath(self):
        self._config.save_directory.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._config.save_directory / f"clipshot_{ts}.png"

    def _save_rendered(self):
        surface = self._render_surface()
        path = self._generate_filepath()
        surface.write_to_png(str(path))
        return path

    def _notify(self, title, body=""):
        subprocess.Popen(
            ["notify-send", "-a", "Clipshot", "-i", "camera-photo-symbolic",
             title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _copy_to_clipboard(self, data, mime_type=None):
        cmd = ["wl-copy"]
        if mime_type:
            cmd += ["--type", mime_type]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if isinstance(data, str):
            data = data.encode()
        proc.stdin.write(data)
        proc.stdin.close()

    def _cleanup_and_close(self):
        if self._screenshot_path:
            try:
                os.unlink(self._screenshot_path)
            except OSError:
                pass
        self.get_application().quit()

    # ── Actions ──────────────────────────────────────────────

    def _action_save(self):
        path = self._save_rendered()
        if path:
            self._notify("Screenshot saved", str(path))
        self._cleanup_and_close()

    def _action_save_copy_path(self):
        path = self._save_rendered()
        if path:
            self._copy_to_clipboard(str(path))
            self._notify("Saved & path copied", str(path))
        self._cleanup_and_close()

    def _action_save_copy_image(self):
        path = self._save_rendered()
        png_bytes = self._render_png_bytes()
        if png_bytes:
            self._copy_to_clipboard(png_bytes, "image/png")
        if path:
            self._notify("Saved & image copied", str(path))
        self._cleanup_and_close()

    def _action_copy_image(self):
        png_bytes = self._render_png_bytes()
        if png_bytes:
            self._copy_to_clipboard(png_bytes, "image/png")
            self._notify("Image copied", "Copied to clipboard as PNG")
        self._cleanup_and_close()
