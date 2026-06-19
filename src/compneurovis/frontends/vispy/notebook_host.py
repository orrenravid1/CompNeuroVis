"""Universal notebook frontend — works in VS Code, JupyterLab, classic Jupyter.

Morphology panel: vispy offscreen → ipywidgets.Image (fast OpenGL coloring).
Trace panel:      ipympl matplotlib figure (interactive zoom/pan, live update).
Combined in an ipywidgets VBox.

Architecture:
    NotebookFrontend    — FrontendBase actor; owns rendering state and widget tree.
    NotebookActorHost   — ActorHost; owns the asyncio poll loop and AppRuntime ref.

Requires: ipympl, ipyevents  (pip install ipympl ipyevents)
"""
from __future__ import annotations

import asyncio
import io
import time
from typing import Any

import numpy as np

from compneurovis.core.app_spec import AppSpec
from compneurovis.core.run_spec import ActorSpec, RunSpec
from compneurovis.core.channel import Channel
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.core.messages import (
    AppSpecDeclared,
    CameraCommand,
    Error,
    FieldReplace,
    InvokeAction,
    Message,
    RenderedFrame,
    RoutedMessage,
    SetControl,
    StopActor,
    command_message,
    make_message,
    update_message,
)
from compneurovis.core.runtime import AppRuntime
from compneurovis.core.runtime_options import env_flag
from compneurovis.frontends.base import FrontendBase
from compneurovis.core.actor_host import ActorHost

POLL_HZ = 30
MAX_SAMPLES = 4000
RENDER_HZ = 15
REMOTE_MORPHOLOGY_FRAME_HZ = 10
# Cap camera-driven (interaction) morph frames. Fast low-res renders would
# otherwise push at the full poll rate during a drag and congest the Jupyter
# comm — intermediate camera moves coalesce into the next scheduled frame.
MORPH_INTERACT_HZ = 12
# RFB pipeline depth: how many frames may be in flight (sent, not yet acked).
# 1 = strict backpressure but throughput is capped by the comm round-trip;
# 2-3 pipelines frames to hide the RTT while staying bounded (no congestion).
MORPH_RFB_MAX_INFLIGHT = 3

# --- TEMP DEBUG ------------------------------------------------------------- #
import os as _os
import traceback as _traceback

_DBG_PATH = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "..", "scratch", "notebook_debug.log")
_DBG_PATH = _os.path.abspath(_DBG_PATH)


def _dbg(msg: str) -> None:
    try:
        with open(_DBG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.monotonic():.3f} [{_os.getpid()}] {msg}\n")
    except Exception:
        pass


try:
    with open(_DBG_PATH, "w", encoding="utf-8") as _fh:
        _fh.write("=== notebook_host debug log ===\n")
except Exception:
    pass
# --- /TEMP DEBUG ------------------------------------------------------------ #


def _ensure_vispy_backend() -> None:
    from vispy.app import _default_app as _da
    if _da.default_app is None:
        from vispy import use
        use(app="pyqt6", gl="gl+")


# --------------------------------------------------------------------------- #
# Actor                                                                        #
# --------------------------------------------------------------------------- #

class NotebookFrontend(FrontendBase):
    """Morphology + trace notebook actor.

    Owns all rendering state. Stateless with respect to the transport — the
    host drives receive / flush / renders via the ActorHost contract.
    """

    def __init__(
        self,
        *,
        dt: float = 0.025,
        segment_index: int = 0,
        morph_size: tuple[int, int] = (800, 320),
        morph_render_scale: float = 1.5,
        trace_figsize: tuple[float, float] = (8, 2.5),
        ylim: tuple[float, float] = (-90.0, 60.0),
        y_label: str = "V (mV)",
        external_morphology_render: bool = False,
    ) -> None:
        super().__init__()
        _dbg(f"NotebookFrontend.__init__ external_morph={external_morphology_render} morph_size={morph_size}")
        self._dt = dt
        self._morph_size = morph_size
        # RFB renders above the canvas display size and lets the client downscale
        # (crisp supersample). Backpressure absorbs the bigger payload — it just
        # self-paces to a lower fps, it never congests. Image path stays 1:1.
        self._morph_render_size = (
            int(round(morph_size[0] * morph_render_scale)),
            int(round(morph_size[1] * morph_render_scale)),
        )
        self._segment_index = segment_index
        self._display_field_id = "segment_display"
        self._voltages: np.ndarray | None = None
        self._buf: list[float] = []
        self._step = 0
        self._last_render = 0.0
        self._last_morph_interact_render = 0.0
        self._render_due = False
        self._morph_dirty = False
        self._app_spec_adopted = False  # geometry/fields consumed (direct or via AppSpecDeclared)
        self.stop_requested = False  # host checks this flag
        self._external_morphology_render = external_morphology_render
        self._last_camera_command = 0.0
        self._camera_command_interval = 1.0 / RENDER_HZ
        self._pending_orbit_dx = 0.0
        self._pending_orbit_dy = 0.0
        self._pending_zoom_scale = 1.0
        self._last_remote_morphology_frame = 0.0
        self._remote_morphology_frame_interval = 1.0 / REMOTE_MORPHOLOGY_FRAME_HZ
        self._trace_interacting = False
        self._trace_resume_at = 0.0
        self._trace_user_view = False

        self._color_map = "scalar"
        self._color_limits: tuple[float, float] | None = (-80.0, 50.0)
        self._color_norm = "auto"

        # ------------------------------------------------------------------ #
        # Morphology panel — vispy offscreen canvas                           #
        # ------------------------------------------------------------------ #
        if not self._external_morphology_render:
            _ensure_vispy_backend()
            from vispy import scene
            from vispy.scene.cameras import TurntableCamera

            canvas = scene.SceneCanvas(
                keys="interactive", bgcolor="black", show=False, size=morph_size,
            )
            view = canvas.central_widget.add_view()
            view.camera = TurntableCamera(
                fov=60, distance=200, elevation=30, azimuth=30,
                translate_speed=100, up="+z",
            )
            self._morph_canvas = canvas
            from compneurovis.frontends.vispy.renderers.morphology import MorphologyRenderer
            self._morph_renderer = MorphologyRenderer(view)
            self._camera = view.camera
        else:
            self._morph_canvas = None
            self._morph_renderer = None
            self._camera = None

        import ipywidgets as widgets

        # Mouse state for drag-to-rotate (Image/ipyevents path only)
        self._mouse_down = False
        self._mouse_last: tuple[int, int] = (0, 0)

        # Backpressure (RFB) path: a canvas anywidget that pulls frames at the
        # rate the client can consume — works in all notebook frontends.
        self._use_rfb = env_flag("CNV_NOTEBOOK_RFB") and not self._external_morphology_render
        self._rfb = None
        self._rfb_inflight = 0  # frames sent but not yet acked (pipeline depth)
        self._morph_pending = False
        self._last_rfb_frame = 0.0
        # TEMP channel-traffic counters (frames out / camera in / ack in / data in)
        self._stat = {"frame": 0, "cam": 0, "ack": 0, "data": 0}
        self._stat_last = 0.0

        if self._use_rfb:
            from compneurovis.frontends.vispy.rfb_widget import MorphRfbWidget
            self._rfb = MorphRfbWidget(width=morph_size[0], height=morph_size[1])
            self._rfb.on_ready(self._on_rfb_ready)
            self._rfb.on_camera(self._on_rfb_camera)
            self._morph_widget = self._rfb
        else:
            self._morph_widget = widgets.Image(
                format="png", width=morph_size[0], height=morph_size[1]
            )
            from ipyevents import Event
            morph_events = Event(
                source=self._morph_widget,
                watched_events=["mousedown", "mouseup", "mousemove", "wheel", "mouseleave", "dragstart"],
                prevent_default_action=True,
                wait=20,
                throttle_or_debounce="throttle",
            )
            morph_events.on_dom_event(self._on_mouse_event)

        # ------------------------------------------------------------------ #
        # Trace panel — ipympl interactive matplotlib figure                  #
        # ------------------------------------------------------------------ #
        import matplotlib
        matplotlib.use("module://ipympl.backend_nbagg")
        import matplotlib.pyplot as plt

        self._plt = plt
        plt.ioff()
        fig, ax = plt.subplots(figsize=trace_figsize)
        fig.patch.set_facecolor("#111111")
        ax.set_facecolor("#111111")
        for spine in ax.spines.values():
            spine.set_color("#555555")
        ax.tick_params(colors="white")
        ax.set_xlabel("t (ms)", color="white")
        ax.set_ylabel(y_label, color="white")
        ax.set_ylim(*ylim)
        (self._trace_line,) = ax.plot([], [], color="#4fc3f7", lw=0.8)
        ax.set_xlim(0, 100)
        fig.tight_layout(pad=0.4)
        self._fig = fig
        self._ax = ax
        fig.canvas.mpl_connect("button_press_event", self._on_trace_interaction_start)
        fig.canvas.mpl_connect("button_release_event", self._on_trace_interaction_end)
        fig.canvas.mpl_connect("scroll_event", self._on_trace_interaction_start)

        # Stop button; host wires up the actual stop() call after start()
        stop_btn = widgets.Button(
            description="Stop", button_style="danger",
            layout=widgets.Layout(width="80px"),
        )
        stop_btn.on_click(lambda _: setattr(self, "stop_requested", True))
        self._widget = widgets.VBox([self._morph_widget, fig.canvas, stop_btn])

    # ---------------------------------------------------------------------- #
    # ActorBase contract                                                       #
    # ---------------------------------------------------------------------- #

    def initialize(self, app_spec: AppSpec | None) -> None:
        # Build-in-child launches pass None here and declare the AppSpec over the
        # channel (AppSpecDeclared) once the worker has built the model. Until then
        # the panel sits in a loading state — the sim is in another process, so the
        # render never blocks on it.
        if app_spec is None:
            _dbg("initialize(None) — awaiting AppSpecDeclared (build-in-child)")
            return
        self._adopt_app_spec(app_spec)

    def _adopt_app_spec(self, app_spec: AppSpec) -> None:
        if self._app_spec_adopted:
            return
        self._app_spec_adopted = True
        _dbg(f"adopt_app_spec geometries={list(app_spec.data.geometries.keys())} fields={list(app_spec.data.fields.keys())}")
        for geo in app_spec.data.geometries.values():
            if isinstance(geo, MorphologyGeometrySpec):
                if self._morph_renderer is not None:
                    self._morph_renderer.set_geometry(geo)
                n = len(geo.positions)
                self._voltages = np.full(n, -65.0, dtype=np.float32)
                break

        field = app_spec.data.fields.get(self._display_field_id)
        if field is not None and field.initial_values is not None:
            vals = np.asarray(field.initial_values, dtype=np.float32)
            if vals.ndim > 1:
                vals = vals[:, -1]
            self._voltages = vals
            if len(vals) > self._segment_index:
                self._buf.append(float(vals[self._segment_index]))

        from compneurovis.core.views import MorphologyViewSpec
        for view_spec in app_spec.view_catalog.views.values():
            if isinstance(view_spec, MorphologyViewSpec):
                self._color_map = view_spec.color_map or "scalar"
                self._color_norm = view_spec.color_norm or "auto"
                if view_spec.color_limits is not None and not isinstance(view_spec.color_limits, str):
                    self._color_limits = tuple(view_spec.color_limits)  # type: ignore[assignment]
                break

        self._build_interaction_widgets(app_spec)

        _dbg(f"adopt_app_spec done voltages={None if self._voltages is None else len(self._voltages)} external={self._external_morphology_render}")
        if self._external_morphology_render:
            return
        if self._use_rfb:
            # Defer to the paced loop — the client emits its first 'ready' on
            # mount; rendering before that would desync the backpressure flag.
            self._morph_pending = True
        else:
            self._render_morph()

    def _build_interaction_widgets(self, app_spec: AppSpec) -> None:
        """Build sliders/dropdowns/buttons from the spec and splice them into the
        widget tree. Each emits a command that the routing sends to the backend."""
        import ipywidgets as widgets
        from compneurovis.core.controls import BoolValueSpec, ChoiceValueSpec, ScalarValueSpec

        rows: list[Any] = []
        for control_id, spec in app_spec.interactions.controls.items():
            vs = spec.value_spec
            if isinstance(vs, ScalarValueSpec):
                lo = float(vs.min) if vs.min is not None else 0.0
                hi = float(vs.max) if vs.max is not None else 1.0
                steps = spec.presentation.steps if spec.presentation else None
                step = (hi - lo) / steps if steps else (hi - lo) / 100.0
                w = widgets.FloatSlider(
                    value=float(vs.default), min=lo, max=hi, step=step,
                    description=spec.label, continuous_update=True, readout_format=".3g",
                    style={"description_width": "initial"}, layout=widgets.Layout(width="95%"),
                )
            elif isinstance(vs, ChoiceValueSpec):
                w = widgets.Dropdown(
                    options=list(vs.options), value=vs.default, description=spec.label,
                    style={"description_width": "initial"},
                )
            elif isinstance(vs, BoolValueSpec):
                w = widgets.Checkbox(value=bool(vs.default), description=spec.label)
            else:
                continue

            def _on_change(change, _cid=control_id):
                self.emit(command_message(SetControl(_cid, change["new"])))

            w.observe(_on_change, names="value")
            rows.append(w)

        for action_id, spec in app_spec.interactions.actions.items():
            btn = widgets.Button(description=spec.label or action_id)

            def _on_click(_b, _aid=action_id):
                self.emit(command_message(InvokeAction(_aid, {})))

            btn.on_click(_on_click)
            rows.append(btn)

        if not rows:
            return
        # Splice the controls in just before the stop button.
        children = list(self._widget.children)
        children.insert(len(children) - 1, widgets.VBox(rows))
        self._widget.children = tuple(children)

    def handle(self, message: Message) -> None:
        payload = message.payload
        if isinstance(payload, Error):
            # The sim/build runs in a child process; a build failure there has
            # nowhere to surface in the kernel otherwise (the app shell just
            # stays empty). Echo the traceback to the kernel's stderr so the
            # cell output shows what went wrong.
            import sys

            sys.stderr.write(f"[CompNeuroVis source error]\n{payload.message.rstrip()}\n")
            sys.stderr.flush()
            return
        if isinstance(payload, AppSpecDeclared):
            self._adopt_app_spec(payload.app_spec)
            return
        if isinstance(payload, RenderedFrame) and payload.frame_id == self._display_field_id:
            now = time.monotonic()
            if now - self._last_remote_morphology_frame < self._remote_morphology_frame_interval:
                return
            self._last_remote_morphology_frame = now
            if self._morph_widget.format != payload.format:
                self._morph_widget.format = payload.format
            self._morph_widget.value = payload.data
            return
        if not (isinstance(payload, FieldReplace) and payload.field_id == self._display_field_id):
            return
        vals = np.asarray(payload.values, dtype=np.float32)
        if vals.ndim > 1:
            vals = vals[:, -1]
        if not self._external_morphology_render:
            self._voltages = vals
        self._buf.append(float(vals[min(self._segment_index, len(vals) - 1)]))
        self._step += 1
        self._render_due = True
        self._morph_pending = True

    # ---------------------------------------------------------------------- #
    # RFB (backpressure) callbacks — fire on the kernel comm handler          #
    # ---------------------------------------------------------------------- #

    def _on_rfb_ready(self) -> None:
        # Client finished painting a frame — one slot freed in the pipeline.
        if self._rfb_inflight > 0:
            self._rfb_inflight -= 1

    def _on_rfb_camera(self, event: dict) -> None:
        _dbg(f"rfb camera {event.get('type')} dx={event.get('dx')} dy={event.get('dy')} delta={event.get('delta')}")
        if self._camera is None:
            return
        kind = event.get("type")
        if kind == "orbit":
            self._camera.azimuth -= float(event.get("dx", 0.0)) * 0.5
            self._camera.elevation = float(
                np.clip(self._camera.elevation + float(event.get("dy", 0.0)) * 0.5, -90, 90)
            )
        elif kind == "zoom":
            # Exponential zoom so it works for both tiny trackpad deltas and big
            # mouse-wheel notches; clamp per event so a large notch can't jump.
            factor = float(np.exp(float(event.get("delta", 0.0)) * 0.01))
            factor = float(np.clip(factor, 0.8, 1.25))
            self._camera.distance *= factor
        self._morph_pending = True

    # ---------------------------------------------------------------------- #
    # Rendering (called by host step loop)                                    #
    # ---------------------------------------------------------------------- #

    def flush_renders(self, now: float) -> None:
        """Render morph+trace if timing is due; render morph if camera dirty."""
        if self._trace_interacting and self._trace_resume_at and now >= self._trace_resume_at:
            self._trace_interacting = False
            self._trace_resume_at = 0.0
        if self._use_rfb:
            self._flush_renders_rfb(now)
            return
        rendered_morph = False
        if self._render_due and now - self._last_render >= 1.0 / RENDER_HZ:
            if not self._external_morphology_render:
                self._render_morph()
                rendered_morph = True
            if self._trace_interacting:
                self._last_render = now
            else:
                self._render_trace()
                self._last_render = now
                self._render_due = False
        if self._morph_dirty and not self._external_morphology_render:
            if rendered_morph:
                # Data render already pushed the latest camera state this tick.
                self._morph_dirty = False
                self._last_morph_interact_render = now
            elif now - self._last_morph_interact_render >= 1.0 / MORPH_INTERACT_HZ:
                self._render_morph()
                self._morph_dirty = False
                self._last_morph_interact_render = now
            # else: stay dirty — coalesce moves into the next scheduled frame.

    def _flush_renders_rfb(self, now: float) -> None:
        """Backpressure-paced render loop. Morph frames are *pulled* — emitted
        only when the client has acked the previous one, so they never queue.
        Camera moves and data updates between acks coalesce into the next pull."""
        # Trace stays on its own rate cap (separate ipympl canvas/comm).
        if self._render_due and now - self._last_render >= 1.0 / RENDER_HZ:
            if not self._trace_interacting:
                self._render_trace()
                self._render_due = False
            self._last_render = now
        # Watchdog: if acks were lost, drain the pipeline after 1s so morph never freezes.
        if self._morph_pending and self._rfb_inflight >= MORPH_RFB_MAX_INFLIGHT and now - self._last_rfb_frame > 1.0:
            _dbg("rfb watchdog: draining pipeline (ack presumed lost)")
            self._rfb_inflight = 0
        # Morph: emit while the pipeline has a free slot and there is something new.
        # Pipelining hides the comm round-trip; depth stays bounded (no congestion).
        if (
            self._morph_pending
            and self._rfb_inflight < MORPH_RFB_MAX_INFLIGHT
            and not self._external_morphology_render
        ):
            self._render_morph()  # sends frame, increments _rfb_inflight
            self._morph_pending = False

    # ---------------------------------------------------------------------- #

    def _on_mouse_event(self, event: dict) -> None:
        etype = event.get("type")
        x, y = event.get("offsetX", 0), event.get("offsetY", 0)
        _dbg(f"mouse {etype} x={x} y={y}")

        if etype == "mousedown":
            self._mouse_down = True
            self._mouse_last = (x, y)
        elif etype in ("mouseup", "mouseleave"):
            if self._external_morphology_render:
                self._emit_pending_camera_command(force=True)
            self._mouse_down = False
        elif etype == "mousemove" and self._mouse_down:
            dx = x - self._mouse_last[0]
            dy = y - self._mouse_last[1]
            self._mouse_last = (x, y)
            if self._external_morphology_render:
                self._pending_orbit_dx += float(dx)
                self._pending_orbit_dy += float(dy)
                self._emit_pending_camera_command()
                return
            if self._camera is None:
                return
            self._camera.azimuth -= dx * 0.5
            self._camera.elevation = float(np.clip(self._camera.elevation + dy * 0.5, -90, 90))
            self._morph_dirty = True
        elif etype == "wheel":
            delta = event.get("deltaY", 0)
            if self._external_morphology_render:
                self._pending_zoom_scale *= float(1.0 + delta * 0.001)
                self._emit_pending_camera_command()
                return
            if self._camera is None:
                return
            self._camera.distance *= 1.0 + delta * 0.001
            self._morph_dirty = True

    def _emit_pending_camera_command(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_camera_command < self._camera_command_interval:
            return
        messages: list[CameraCommand] = []
        if self._pending_orbit_dx or self._pending_orbit_dy:
            messages.append(
                CameraCommand(
                    self._display_field_id,
                    "orbit",
                    dx=self._pending_orbit_dx,
                    dy=self._pending_orbit_dy,
                )
            )
            self._pending_orbit_dx = 0.0
            self._pending_orbit_dy = 0.0
        if self._pending_zoom_scale != 1.0:
            messages.append(
                CameraCommand(
                    self._display_field_id,
                    "zoom",
                    scale=self._pending_zoom_scale,
                )
            )
            self._pending_zoom_scale = 1.0
        if not messages:
            return
        self._last_camera_command = now
        for command in messages:
            self.emit(
                make_message(
                    "command",
                    RoutedMessage("renderer", command_message(command)),
                )
            )

    def _on_trace_interaction_start(self, _event) -> None:
        self._trace_interacting = True
        self._trace_user_view = True
        self._trace_resume_at = time.monotonic() + 0.4

    def _on_trace_interaction_end(self, _event) -> None:
        self._trace_interacting = False
        self._trace_resume_at = 0.0
        self._render_due = True

    def _render_morph(self) -> None:
        if self._morph_canvas is None or self._morph_renderer is None:
            _dbg(f"_render_morph SKIP canvas={self._morph_canvas is not None} renderer={self._morph_renderer is not None}")
            return
        try:
            t0 = time.monotonic()
            if self._voltages is not None:
                self._morph_renderer.update_colors(
                    self._voltages, self._color_map,
                    color_limits=self._color_limits, color_norm=self._color_norm,
                )
            t1 = time.monotonic()
            render_size = self._morph_render_size if self._use_rfb else self._morph_size
            rgb = self._morph_canvas.render(size=render_size, alpha=False)
            t2 = time.monotonic()
            buf = io.BytesIO()
            from PIL import Image
            Image.fromarray(rgb).save(buf, format="JPEG", quality=70, optimize=False)
            data = buf.getvalue()
            t3 = time.monotonic()
            _dbg(
                f"_render_morph TIMING colors={int((t1-t0)*1000)}ms "
                f"render={int((t2-t1)*1000)}ms encode={int((t3-t2)*1000)}ms total={int((t3-t0)*1000)}ms"
            )
            if self._use_rfb:
                self._rfb_inflight += 1  # one more frame in the pipeline until acked
                self._last_rfb_frame = time.monotonic()
                self._rfb.send_frame(data)
            else:
                if self._morph_widget.format != "jpeg":
                    self._morph_widget.format = "jpeg"
                self._morph_widget.value = data
            _dbg(f"_render_morph OK rgb={rgb.shape} bytes={len(data)} rfb={self._use_rfb}")
        except Exception:
            _dbg("_render_morph EXC\n" + _traceback.format_exc())
            raise

    def _render_trace(self) -> None:
        y = np.asarray(self._buf[-MAX_SAMPLES:], dtype=np.float32)
        n = len(y)
        if n < 2:
            return
        t_end = self._step * self._dt
        t_start = max(0.0, t_end - n * self._dt)
        x = np.linspace(t_start, t_end, n)
        self._trace_line.set_data(x, y)
        if not self._trace_user_view:
            self._ax.set_xlim(max(0.0, t_end - MAX_SAMPLES * self._dt), max(t_end, 10.0))
        self._fig.canvas.draw_idle()


class NotebookMorphologyRenderActor(FrontendBase):
    """Subprocess-capable morphology renderer for notebook widgets."""

    def __init__(self, *, morph_size: tuple[int, int] = (800, 320)) -> None:
        super().__init__()
        self._display_field_id = "segment_display"
        self._morph_size = morph_size
        self._morph_canvas = None
        self._morph_renderer = None
        self._camera = None
        self._color_map = "scalar"
        self._color_limits: tuple[float, float] | None = (-80.0, 50.0)
        self._color_norm = "auto"
        self._last_render = 0.0

    def initialize(self, app_spec: AppSpec) -> None:
        _ensure_vispy_backend()
        from vispy import scene
        from vispy.scene.cameras import TurntableCamera
        from compneurovis.frontends.vispy.renderers.morphology import MorphologyRenderer
        from compneurovis.core.views import MorphologyViewSpec

        canvas = scene.SceneCanvas(keys="interactive", bgcolor="black", show=False, size=self._morph_size)
        view = canvas.central_widget.add_view()
        view.camera = TurntableCamera(
            fov=60,
            distance=200,
            elevation=30,
            azimuth=30,
            translate_speed=100,
            up="+z",
        )
        self._morph_canvas = canvas
        self._morph_renderer = MorphologyRenderer(view)
        self._camera = view.camera

        for view_spec in app_spec.view_catalog.views.values():
            if isinstance(view_spec, MorphologyViewSpec):
                self._display_field_id = view_spec.color_field_id or self._display_field_id
                self._color_map = view_spec.color_map or "scalar"
                self._color_norm = view_spec.color_norm or "auto"
                if view_spec.color_limits is not None and not isinstance(view_spec.color_limits, str):
                    self._color_limits = tuple(view_spec.color_limits)  # type: ignore[assignment]
                break

        for geo in app_spec.data.geometries.values():
            if isinstance(geo, MorphologyGeometrySpec):
                self._morph_renderer.set_geometry(geo)
                break

        field = app_spec.data.fields.get(self._display_field_id)
        if field is not None and field.initial_values is not None:
            self._render_values(np.asarray(field.initial_values, dtype=np.float32))

    def handle(self, message: Message) -> None:
        payload = message.payload
        if isinstance(payload, CameraCommand) and payload.target_id == self._display_field_id:
            self._handle_camera_command(payload)
            return
        if not (isinstance(payload, FieldReplace) and payload.field_id == self._display_field_id):
            return
        now = time.monotonic()
        if now - self._last_render < 1.0 / RENDER_HZ:
            return
        self._render_values(np.asarray(payload.values, dtype=np.float32))
        self._last_render = now

    def _handle_camera_command(self, command: CameraCommand) -> None:
        if self._camera is None:
            return
        if command.kind == "orbit":
            self._camera.azimuth -= command.dx * 0.5
            self._camera.elevation = float(np.clip(self._camera.elevation + command.dy * 0.5, -90, 90))
        elif command.kind == "zoom":
            self._camera.distance *= command.scale
        elif command.kind == "reset":
            self._camera.azimuth = 30
            self._camera.elevation = 30
            self._camera.distance = 200
        now = time.monotonic()
        if now - self._last_render < 1.0 / RENDER_HZ:
            return
        self._render_current()
        self._last_render = now

    def _render_current(self) -> None:
        if self._morph_canvas is None:
            return
        rgba = self._morph_canvas.render()
        self._emit_frame(rgba)

    def _render_values(self, values: np.ndarray) -> None:
        if self._morph_canvas is None or self._morph_renderer is None:
            return
        if values.ndim > 1:
            values = values[:, -1]
        self._morph_renderer.update_colors(
            values,
            self._color_map,
            color_limits=self._color_limits,
            color_norm=self._color_norm,
        )
        rgba = self._morph_canvas.render()
        self._emit_frame(rgba)

    def _emit_frame(self, rgba: np.ndarray) -> None:
        buf = io.BytesIO()
        from PIL import Image

        Image.fromarray(rgba[:, :, :3]).save(buf, format="JPEG", quality=70, optimize=False)
        self.emit_update(
            RenderedFrame(
                frame_id=self._display_field_id,
                data=buf.getvalue(),
                format="jpeg",
                width=int(rgba.shape[1]),
                height=int(rgba.shape[0]),
            )
        )

    def emit_update(self, payload) -> None:
        self.emit(update_message(payload))


# --------------------------------------------------------------------------- #
# Host                                                                         #
# --------------------------------------------------------------------------- #

class NotebookActorHost(ActorHost):
    """Drives the notebook actor. Mirrors VispyActorHost for Qt.

    Owns the asyncio poll loop and holds an AppRuntime reference for
    coordinated startup/shutdown. The channel is injectable —
    in-process queue today, WebSocket tomorrow.
    """

    def __init__(
        self,
        runtime: AppRuntime,
        channel: Channel,
        *,
        dt: float = 0.025,
        segment_index: int = 0,
        morph_size: tuple[int, int] = (800, 320),
        trace_figsize: tuple[float, float] = (8, 2.5),
        ylim: tuple[float, float] = (-90.0, 60.0),
        y_label: str = "V (mV)",
        external_morphology_render: bool = False,
    ) -> None:
        super().__init__(channel=channel)
        self._runtime = runtime
        self._frontend_kwargs = dict(
            dt=dt,
            segment_index=segment_index,
            morph_size=morph_size,
            trace_figsize=trace_figsize,
            ylim=ylim,
            y_label=y_label,
            external_morphology_render=external_morphology_render,
        )
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        actor_source = lambda: NotebookFrontend(**self._frontend_kwargs)
        super().start(actor_source, self._runtime.app_spec)
        self._running = True

    def run(self) -> Any:
        """Kick off asyncio poll loop and return the VBox widget."""
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._poll_loop())
        return self._notebook_frontend()._widget

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self.channel is not None:
            try:
                self.channel.send(command_message(StopActor()))
                self.channel.send(
                    make_message(
                        "command",
                        RoutedMessage("renderer", command_message(StopActor())),
                    )
                )
            except Exception:
                pass
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._runtime.stop()
        super().stop()

    def receive(self) -> None:
        actor = self._notebook_frontend()
        if self.channel is None:
            return
        latest_rendered_frames: dict[str, Message] = {}
        for message in self.channel.poll():
            payload = message.payload
            if isinstance(payload, StopActor):
                self._stop_requested = True
                self._running = False
                self._runtime.stop()
                return
            if isinstance(payload, RenderedFrame):
                latest_rendered_frames[payload.frame_id] = message
            else:
                actor.handle(message)
        for message in latest_rendered_frames.values():
            actor.handle(message)

    def flush(self) -> None:
        actor = self._notebook_frontend()
        if self.channel is None:
            actor.take_outbound_messages()
            return
        latest_camera_messages: dict[str, Message] = {}
        for message in actor.take_outbound_messages():
            payload = message.payload
            if (
                isinstance(payload, RoutedMessage)
                and isinstance(payload.message.payload, CameraCommand)
            ):
                latest_camera_messages[payload.message.payload.kind] = message
            else:
                self.channel.send(message)
        for message in latest_camera_messages.values():
            self.channel.send(message)

    async def _poll_loop(self) -> None:
        interval = 1.0 / POLL_HZ
        frontend = self._notebook_frontend()
        _dbg("_poll_loop START")
        ticks = 0
        while self._running:
            if frontend.stop_requested:
                self.stop()
                break
            try:
                ta = time.monotonic()
                self.receive()
                tb = time.monotonic()
                frontend.flush_renders(tb)
                tc = time.monotonic()
                self.flush()
                td = time.monotonic()
                recv_ms = (tb - ta) * 1000
                flush_ms = (tc - tb) * 1000
                if recv_ms > 50 or flush_ms > 50:
                    _dbg(f"_poll_loop SLOW receive={int(recv_ms)}ms flush_renders={int(flush_ms)}ms send={int((td-tc)*1000)}ms")
            except (BrokenPipeError, OSError):
                _dbg("_poll_loop transport closed")
                self._running = False
                break
            except Exception:
                _dbg("_poll_loop EXC\n" + _traceback.format_exc())
                self._running = False
                break
            ticks += 1
            if ticks % 30 == 0:
                _dbg(f"_poll_loop alive ticks={ticks}")
            await asyncio.sleep(interval)
        _dbg(f"_poll_loop END running={self._running}")

    def _notebook_frontend(self) -> NotebookFrontend:
        actor = self._actor()
        if not isinstance(actor, NotebookFrontend):
            raise TypeError(f"NotebookActorHost expected NotebookFrontend, got {type(actor)!r}")
        return actor


# --------------------------------------------------------------------------- #
# Launch helper                                                                #
# --------------------------------------------------------------------------- #

def _launch_notebook(
    *,
    backend_factory,
    app_spec: AppSpec,
    dt: float = 0.025,
) -> Any:
    """Start backend actor + notebook frontend and return the VBox widget.

    Compiles to a RunSpec and calls start_app() so the full architecture
    (AppRuntime, ActorSpec, transport) is exercised uniformly.

    Parameters
    ----------
    backend_factory : zero-arg callable returning a BackendBase instance
    app_spec        : AppSpec built from the backend before calling this
    dt              : simulation timestep in ms (for the trace time axis)
    """
    from compneurovis.core.actor_launchers import ActorProcess, ThreadActorLauncher, assert_spawn_picklable
    from compneurovis.core.run import start_app
    from compneurovis.core.bus import bus_transport
    from compneurovis.core.run_spec import MessageMatch, RouteSpec, RoutingSpec

    routes: list[RouteSpec] = []
    for control_id, control in app_spec.interactions.controls.items():
        if control.send_to_backend:
            routes.append(
                RouteSpec(
                    match=MessageMatch(
                        intent="command",
                        message_type="set_control",
                        attrs={"control_id": control_id},
                    ),
                    targets=("backend",),
                )
            )
    for action_id in app_spec.interactions.actions:
        routes.append(
            RouteSpec(
                match=MessageMatch(
                    intent="command",
                    message_type="invoke_action",
                    attrs={"action_id": action_id},
                ),
                targets=("backend",),
            )
        )
    routes.extend(
        (
            RouteSpec(
                match=MessageMatch(intent="command"),
                targets=("backend",),
            ),
            RouteSpec(
                match=MessageMatch(intent="update"),
                targets=("frontend",),
            ),
        )
    )
    routing = RoutingSpec(routes=tuple(routes))
    use_backend_process = env_flag("CNV_NOTEBOOK_BACKEND_PROCESS")
    if use_backend_process:
        assert_spawn_picklable(backend_factory, label="notebook backend factory")

    handle = start_app(RunSpec(
        app_spec=app_spec,
        actors=[
            ActorSpec(
                id="backend",
                host_source=(
                    lambda r, ch, _f=backend_factory: ActorProcess(
                        actor_source=_f,
                        app_spec=r.app_spec,
                        channel=ch,
                        diagnostics=r.diagnostics,
                    )
                    if use_backend_process
                    else ThreadActorLauncher(_f, r, ch)
                ),
            ),
            ActorSpec(
                id="frontend",
                host_source=lambda r, ch: NotebookActorHost(r, ch, dt=dt),
                runs_in_foreground=False,
            ),
        ],
        transport=bus_transport(mode="pipe" if use_backend_process else "inprocess"),
        routing=routing,
    ))
    return handle.widget("frontend")


__all__ = ["NotebookActorHost", "NotebookFrontend", "NotebookMorphologyRenderActor"]
