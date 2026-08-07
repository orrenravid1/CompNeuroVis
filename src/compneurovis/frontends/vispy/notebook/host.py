"""Notebook frontend for source-level CompNeuroVis apps.

The default notebook actor owns the ipywidgets control surface. Depending on
runtime flags, heavy rendering can happen either in the kernel or in child
process actors:

- morphology: VisPy offscreen render to an image widget
- trace: Matplotlib/Agg render to an image widget, or ipympl in-kernel fallback

In render-process mode, the notebook kernel receives pre-rendered image frames
and forwards controls/camera commands; simulation and plot drawing do not run in
the kernel event loop.
"""
from __future__ import annotations

import asyncio
import io
import time
import traceback
from typing import Any, Mapping

import numpy as np

from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.app_spec import AppSpec, app_ref
from compneurovis.core.run_spec import ActorSpec, RunSpec
from compneurovis.core.runtime.channel import Channel
from compneurovis.geometries.morphology import (
    morphology_geometry_from_spec,
)
from compneurovis.core.messages import (
    AppSpecDeclared,
    CameraCommand,
    Error,
    FieldAppend,
    FieldReplace,
    InvokeAction,
    Message,
    RenderedFrame,
    RoutedMessage,
    StopActor,
    ValueChange,
    command_message,
    make_message,
    update_message,
)
from compneurovis.core.runtime import AppRuntime
from compneurovis.core.runtime.options import env_flag, env_int
from compneurovis.frontends.base import FrontendBase
from compneurovis.core.runtime.actor_host import ActorHost

POLL_HZ = 30
MAX_SAMPLES = 4000
RENDER_HZ = 15
REMOTE_MORPHOLOGY_FRAME_HZ = 10
LINE_PLOT_FRAME_ID = "notebook_line_plot"
LINE_PLOT_RENDER_DPI = env_int("CNV_NOTEBOOK_LINE_PLOT_DPI", 150, minimum=72, maximum=240)
LINE_PLOT_JPEG_QUALITY = env_int("CNV_NOTEBOOK_LINE_PLOT_QUALITY", 90, minimum=60, maximum=95)
# Cap camera-driven (interaction) morph frames. Fast low-res renders would
# otherwise push at the full poll rate during a drag and congest the Jupyter
# comm — intermediate camera moves coalesce into the next scheduled frame.
MORPH_INTERACT_HZ = 12
# RFB pipeline depth: how many frames may be in flight (sent, not yet acked).
# 1 = strict backpressure but throughput is capped by the comm round-trip;
# 2-3 pipelines frames to hide the RTT while staying bounded (no congestion).
MORPH_RFB_MAX_INFLIGHT = 3





def _command_ref(value: Any) -> tuple[str, dict[str, Any]]:
    ref = app_ref(value)
    return ref.id, {"fragment_id": ref.fragment_id}

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
        line_plot_figsize: tuple[float, float] = (8, 2.5),
        ylim: tuple[float, float] = (-90.0, 60.0),
        y_label: str = "V (mV)",
        external_morphology_render: bool = False,
        external_line_plot_render: bool = False,
    ) -> None:
        super().__init__()
        perf_log("notebook_frontend", "initialize", external_morphology_render=external_morphology_render, external_line_plot_render=external_line_plot_render, morph_width=morph_size[0], morph_height=morph_size[1])
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
        self._external_line_plot_render = external_line_plot_render
        self._last_camera_command = 0.0
        self._camera_command_interval = 1.0 / RENDER_HZ
        self._pending_orbit_dx = 0.0
        self._pending_orbit_dy = 0.0
        self._pending_zoom_scale = 1.0
        self._last_remote_morphology_frame = 0.0
        self._remote_morphology_frame_interval = 1.0 / REMOTE_MORPHOLOGY_FRAME_HZ
        self._line_plot_interacting = False
        self._line_plot_resume_at = 0.0
        self._line_plot_user_view = False

        self._color_map = "scalar"
        self._default_color_map = self._color_map
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
            from compneurovis.components.morphology.renderer import MorphologyRenderer
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
        self._morph_events = None

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
            from compneurovis.frontends.vispy.notebook.rfb import MorphRfbWidget
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
            self._morph_events = morph_events

        # ------------------------------------------------------------------ #
        # Trace panel                                                         #
        # ------------------------------------------------------------------ #
        if self._external_line_plot_render:
            self._line_plot_widget = widgets.Image(
                format="jpeg",
                width=int(line_plot_figsize[0] * 100),
                height=int(line_plot_figsize[1] * 100),
            )
            self._plt = None
            self._fig = None
            self._ax = None
            self._line_plot_line = None
        else:
            import matplotlib
            matplotlib.use("module://ipympl.backend_nbagg")
            import matplotlib.pyplot as plt

            self._plt = plt
            plt.ioff()
            fig, ax = plt.subplots(figsize=line_plot_figsize)
            fig.patch.set_facecolor("#111111")
            ax.set_facecolor("#111111")
            for spine in ax.spines.values():
                spine.set_color("#555555")
            ax.tick_params(colors="white")
            ax.set_xlabel("t (ms)", color="white")
            ax.set_ylabel(y_label, color="white")
            ax.set_ylim(*ylim)
            (self._line_plot_line,) = ax.plot([], [], color="#4fc3f7", lw=0.8)
            ax.set_xlim(0, 100)
            fig.tight_layout(pad=0.4)
            self._fig = fig
            self._ax = ax
            fig.canvas.mpl_connect("button_press_event", self._on_line_plot_interaction_start)
            fig.canvas.mpl_connect("button_release_event", self._on_line_plot_interaction_end)
            fig.canvas.mpl_connect("scroll_event", self._on_line_plot_interaction_start)
            self._line_plot_widget = fig.canvas

        # Stop button; host wires up the actual stop() call after start()
        stop_btn = widgets.Button(
            description="Stop", button_style="danger",
            layout=widgets.Layout(width="80px"),
        )
        stop_btn.on_click(lambda _: setattr(self, "stop_requested", True))
        self._widget = widgets.VBox([self._morph_widget, self._line_plot_widget, stop_btn])

    # ---------------------------------------------------------------------- #
    # ActorBase contract                                                       #
    # ---------------------------------------------------------------------- #

    def shutdown(self) -> None:
        events = getattr(self, "_morph_events", None)
        close = getattr(events, "close", None)
        if callable(close):
            close()
        rfb = getattr(self, "_rfb", None)
        close = getattr(rfb, "close", None)
        if callable(close):
            close()

    def initialize(self, app_spec: AppSpec | None) -> None:
        # Build-in-child launches pass None here and declare the AppSpec over the
        # channel (AppSpecDeclared) once the worker has built the model. Until then
        # the panel sits in a loading state — the sim is in another process, so the
        # render never blocks on it.
        if app_spec is None:
            perf_log("notebook_frontend", "await_app_spec_declared")
            return
        self._adopt_app_spec(app_spec)

    def _adopt_app_spec(self, app_spec: AppSpec) -> None:
        if self._app_spec_adopted:
            return
        self._app_spec_adopted = True
        perf_log("notebook_frontend", "adopt_app_spec", geometries=list(app_spec.data.geometries.keys()), fields=list(app_spec.data.fields.keys()))
        for spec in app_spec.data.geometries.values():
            geo = morphology_geometry_from_spec(spec)
            if geo is not None:
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
            if not self._external_line_plot_render and len(vals) > self._segment_index:
                self._buf.append(float(vals[self._segment_index]))

        from compneurovis.frontends.vispy.registries.render_configs import view_render_config
        from compneurovis.components.morphology.vispy import MorphologyRenderConfig
        for raw_view in app_spec.view_catalog.views.values():
            view_spec = view_render_config(raw_view)
            if isinstance(view_spec, MorphologyRenderConfig):
                self._display_field_id = view_spec.color_field_id or self._display_field_id
                self._color_map = view_spec.color_map or "scalar"
                self._default_color_map = self._color_map
                self._color_norm = view_spec.color_norm or "auto"
                if view_spec.color_limits is not None and not isinstance(view_spec.color_limits, str):
                    self._color_limits = tuple(view_spec.color_limits)  # type: ignore[assignment]
                break
        color_field = app_spec.data.fields.get(self._display_field_id)
        if color_field is not None:
            self._apply_color_field_attrs(color_field.attrs)

        self._build_interaction_widgets(app_spec)

        perf_log("notebook_frontend", "adopt_app_spec_complete", voltage_count=None if self._voltages is None else len(self._voltages), external_morphology_render=self._external_morphology_render)
        if self._external_morphology_render:
            return
        if self._use_rfb:
            # Defer to the paced loop — the client emits its first 'ready' on
            # mount; rendering before that would desync the backpressure flag.
            self._morph_pending = True
        else:
            self._render_morph()

    def _apply_color_field_attrs(self, attrs: Mapping[str, Any]) -> None:
        if "color_map" in attrs:
            self._color_map = str(attrs.get("color_map") or self._default_color_map)
        if "color_limits" in attrs:
            limits = attrs.get("color_limits")
            self._color_limits = None if limits is None else (float(limits[0]), float(limits[1]))

    def _build_interaction_widgets(self, app_spec: AppSpec) -> None:
        """Build sliders/dropdowns/buttons from the spec and splice them into the
        widget tree. Each emits a command that the routing sends to the backend."""
        import ipywidgets as widgets

        rows: list[Any] = []
        for control_id, spec in app_spec.interactions.controls.items():
            vs = spec.value_spec
            presentation_kind = spec.presentation.kind
            if presentation_kind == "slider":
                lo = float(vs.property("min", 0.0))
                hi = float(vs.property("max", 1.0))
                steps = int(spec.presentation.property("steps", 100))
                step = (hi - lo) / max(1, steps)
                widget_type = (
                    widgets.IntSlider
                    if vs.property("value_type") == "int"
                    else widgets.FloatSlider
                )
                w = widget_type(
                    value=vs.default, min=lo, max=hi, step=step,
                    description=spec.label, continuous_update=True, readout_format=".3g",
                    style={"description_width": "initial"}, layout=widgets.Layout(width="95%"),
                )
            elif presentation_kind == "spinbox":
                w = widgets.BoundedIntText(
                    value=int(vs.default),
                    min=int(vs.property("min", 0)),
                    max=int(vs.property("max", 100)),
                    description=spec.label,
                    style={"description_width": "initial"},
                )
            elif presentation_kind == "dropdown":
                w = widgets.Dropdown(
                    options=list(vs.property("options", ())),
                    value=vs.default,
                    description=spec.label,
                    style={"description_width": "initial"},
                )
            elif presentation_kind == "checkbox":
                w = widgets.Checkbox(value=bool(vs.default), description=spec.label)
            elif presentation_kind == "text":
                w = widgets.Text(
                    value=str(vs.default),
                    placeholder=str(vs.property("placeholder", "")),
                    description=spec.label,
                    style={"description_width": "initial"},
                )
            else:
                continue

            def _on_change(change, _value_key=spec.resolved_value_key()):
                local_key, tags = _command_ref(_value_key)
                self.emit(command_message(ValueChange({local_key: change["new"]}), tags=tags))
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
            perf_log("notebook_frontend", "morphology_frame_received", frame_id=payload.frame_id, bytes=len(payload.data), width=payload.width, height=payload.height)
            return
        if isinstance(payload, RenderedFrame) and payload.frame_id == LINE_PLOT_FRAME_ID:
            if self._line_plot_widget.format != payload.format:
                self._line_plot_widget.format = payload.format
            if payload.width is not None:
                self._line_plot_widget.width = int(payload.width)
            if payload.height is not None:
                self._line_plot_widget.height = int(payload.height)
            self._line_plot_widget.value = payload.data
            perf_log("notebook_frontend", "line_plot_frame_received", frame_id=payload.frame_id, bytes=len(payload.data), width=payload.width, height=payload.height)
            return
        if isinstance(payload, RenderedFrame):
            perf_log("notebook_frontend", "rendered_frame_ignored", frame_id=payload.frame_id, expected_morphology_frame_id=self._display_field_id, line_plot_frame_id=LINE_PLOT_FRAME_ID, bytes=len(payload.data))
            return
        if not (isinstance(payload, FieldReplace) and payload.field_id == self._display_field_id):
            return
        self._apply_color_field_attrs(payload.attrs_update)
        vals = np.asarray(payload.values, dtype=np.float32)
        if vals.ndim > 1:
            vals = vals[:, -1]
        if not self._external_morphology_render:
            self._voltages = vals
        if not self._external_line_plot_render:
            self._buf.append(float(vals[min(self._segment_index, len(vals) - 1)]))
            self._step += 1
            self._render_due = True
        if not self._external_morphology_render:
            self._morph_pending = True

    # ---------------------------------------------------------------------- #
    # RFB (backpressure) callbacks — fire on the kernel comm handler          #
    # ---------------------------------------------------------------------- #

    def _on_rfb_ready(self) -> None:
        # Client finished painting a frame — one slot freed in the pipeline.
        if self._rfb_inflight > 0:
            self._rfb_inflight -= 1

    def _on_rfb_camera(self, event: dict) -> None:
        perf_log("notebook_frontend", "rfb_camera", kind=event.get("type"), dx=event.get("dx"), dy=event.get("dy"), delta=event.get("delta"))
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
        if self._line_plot_interacting and self._line_plot_resume_at and now >= self._line_plot_resume_at:
            self._line_plot_interacting = False
            self._line_plot_resume_at = 0.0
        if self._use_rfb:
            self._flush_renders_rfb(now)
            return
        rendered_morph = False
        if self._render_due and now - self._last_render >= 1.0 / RENDER_HZ:
            if not self._external_morphology_render:
                self._render_morph()
                rendered_morph = True
            if self._line_plot_interacting:
                self._last_render = now
            else:
                if not self._external_line_plot_render:
                    self._render_line_plot()
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
            if not self._line_plot_interacting:
                if not self._external_line_plot_render:
                    self._render_line_plot()
                self._render_due = False
            self._last_render = now
        # Watchdog: if acks were lost, drain the pipeline after 1s so morph never freezes.
        if self._morph_pending and self._rfb_inflight >= MORPH_RFB_MAX_INFLIGHT and now - self._last_rfb_frame > 1.0:
            perf_log("notebook_frontend", "rfb_watchdog_drain", inflight=self._rfb_inflight)
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
        perf_log("notebook_frontend", "mouse", kind=etype, x=x, y=y)

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

    def _on_line_plot_interaction_start(self, _event) -> None:
        self._line_plot_interacting = True
        self._line_plot_user_view = True
        self._line_plot_resume_at = time.monotonic() + 0.4

    def _on_line_plot_interaction_end(self, _event) -> None:
        self._line_plot_interacting = False
        self._line_plot_resume_at = 0.0
        self._render_due = True

    def _render_morph(self) -> None:
        if self._morph_canvas is None or self._morph_renderer is None:
            perf_log("notebook_frontend", "render_morph_skip", has_canvas=self._morph_canvas is not None, has_renderer=self._morph_renderer is not None)
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
            perf_log(
                "notebook_frontend",
                "render_morph_timing",
                colors_ms=round((t1 - t0) * 1000, 3),
                render_ms=round((t2 - t1) * 1000, 3),
                encode_ms=round((t3 - t2) * 1000, 3),
                total_ms=round((t3 - t0) * 1000, 3),
            )
            if self._use_rfb:
                self._rfb_inflight += 1  # one more frame in the pipeline until acked
                self._last_rfb_frame = time.monotonic()
                self._rfb.send_frame(data)
            else:
                if self._morph_widget.format != "jpeg":
                    self._morph_widget.format = "jpeg"
                self._morph_widget.value = data
            perf_log("notebook_frontend", "render_morph_frame", rgb_shape=rgb.shape, bytes=len(data), rfb=self._use_rfb)
        except Exception as exc:
            perf_log(
                "notebook_frontend",
                "render_morph_error",
                error_type=type(exc).__name__,
                message=str(exc),
                traceback="".join(traceback.format_exception(exc)),
            )
            raise

    def _render_line_plot(self) -> None:
        if self._external_line_plot_render or self._line_plot_line is None or self._ax is None or self._fig is None:
            return
        y = np.asarray(self._buf[-MAX_SAMPLES:], dtype=np.float32)
        n = len(y)
        if n < 2:
            return
        t_end = self._step * self._dt
        t_start = max(0.0, t_end - n * self._dt)
        x = np.linspace(t_start, t_end, n)
        self._line_plot_line.set_data(x, y)
        if not self._line_plot_user_view:
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
        self._default_color_map = self._color_map
        self._color_limits: tuple[float, float] | None = (-80.0, 50.0)
        self._color_norm = "auto"
        self._last_render = 0.0
        self._pending_values: np.ndarray | None = None
        self._render_requested = False

    def initialize(self, app_spec: AppSpec | None) -> None:
        perf_log("notebook_morphology_renderer", "initialize", has_app_spec=app_spec is not None)
        if app_spec is not None:
            self._adopt_app_spec(app_spec)

    def _ensure_renderer(self) -> None:
        if self._morph_canvas is not None:
            return
        _ensure_vispy_backend()
        from vispy import scene
        from vispy.scene.cameras import TurntableCamera
        from compneurovis.components.morphology.renderer import MorphologyRenderer

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

    def _adopt_app_spec(self, app_spec: AppSpec) -> None:
        self._ensure_renderer()
        perf_log("notebook_morphology_renderer", "adopt_app_spec", geometries=list(app_spec.data.geometries.keys()), fields=list(app_spec.data.fields.keys()))
        from compneurovis.frontends.vispy.registries.render_configs import view_render_config
        from compneurovis.components.morphology.vispy import MorphologyRenderConfig

        for raw_view in app_spec.view_catalog.views.values():
            view_spec = view_render_config(raw_view)
            if isinstance(view_spec, MorphologyRenderConfig):
                self._display_field_id = view_spec.color_field_id or self._display_field_id
                self._color_map = view_spec.color_map or "scalar"
                self._default_color_map = self._color_map
                self._color_norm = view_spec.color_norm or "auto"
                if view_spec.color_limits is not None and not isinstance(view_spec.color_limits, str):
                    self._color_limits = tuple(view_spec.color_limits)  # type: ignore[assignment]
                break
        color_field = app_spec.data.fields.get(self._display_field_id)
        if color_field is not None:
            self._apply_color_field_attrs(color_field.attrs)

        for spec in app_spec.data.geometries.values():
            geo = morphology_geometry_from_spec(spec)
            if geo is not None:
                self._morph_renderer.set_geometry(geo)
                break

        field = app_spec.data.fields.get(self._display_field_id)
        if field is not None and field.initial_values is not None:
            self._pending_values = np.asarray(field.initial_values, dtype=np.float32)
            self._render_requested = True
            perf_log("notebook_morphology_renderer", "initial_field_ready", field_id=self._display_field_id, value_shape=np.asarray(field.initial_values).shape)

    def _apply_color_field_attrs(self, attrs: Mapping[str, Any]) -> None:
        if "color_map" in attrs:
            self._color_map = str(attrs.get("color_map") or self._default_color_map)
        if "color_limits" in attrs:
            limits = attrs.get("color_limits")
            self._color_limits = None if limits is None else (float(limits[0]), float(limits[1]))

    def handle(self, message: Message) -> None:
        payload = message.payload
        if isinstance(payload, AppSpecDeclared):
            perf_log("notebook_morphology_renderer", "app_spec_declared")
            self._adopt_app_spec(payload.app_spec)
            return
        if isinstance(payload, CameraCommand) and payload.target_id == self._display_field_id:
            self._handle_camera_command(payload)
            return
        if not (isinstance(payload, FieldReplace) and payload.field_id == self._display_field_id):
            if isinstance(payload, FieldReplace):
                perf_log("notebook_morphology_renderer", "field_replace_ignored", field_id=payload.field_id, expected_field_id=self._display_field_id)
            return
        self._apply_color_field_attrs(payload.attrs_update)
        self._pending_values = np.asarray(payload.values, dtype=np.float32)
        self._render_requested = True

    def tick(self) -> None:
        if not self._render_requested:
            return
        now = time.monotonic()
        if now - self._last_render < 1.0 / RENDER_HZ:
            return
        if self._pending_values is not None:
            values = self._pending_values
            self._pending_values = None
            self._render_values(values)
        else:
            self._render_current()
        self._render_requested = False
        self._last_render = now

    def is_active(self) -> bool:
        return True

    def idle_sleep(self) -> float:
        return 1.0 / 60.0

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
        self._render_requested = True

    def _render_current(self) -> None:
        if self._morph_canvas is None:
            return
        rgba = self._morph_canvas.render()
        self._emit_frame(rgba)

    def _render_values(self, values: np.ndarray) -> None:
        if self._morph_canvas is None or self._morph_renderer is None:
            perf_log("notebook_morphology_renderer", "render_values_skip", has_canvas=self._morph_canvas is not None, has_renderer=self._morph_renderer is not None)
            return
        try:
            t0 = time.monotonic()
            if values.ndim > 1:
                values = values[:, -1]
            self._morph_renderer.update_colors(
                values,
                self._color_map,
                color_limits=self._color_limits,
                color_norm=self._color_norm,
            )
            t1 = time.monotonic()
            rgba = self._morph_canvas.render()
            t2 = time.monotonic()
            self._emit_frame(rgba)
            t3 = time.monotonic()
            perf_log(
                "notebook_morphology_renderer",
                "render_values_timing",
                field_id=self._display_field_id,
                value_shape=values.shape,
                colors_ms=round((t1 - t0) * 1000, 3),
                render_ms=round((t2 - t1) * 1000, 3),
                emit_ms=round((t3 - t2) * 1000, 3),
                total_ms=round((t3 - t0) * 1000, 3),
            )
        except Exception as exc:
            perf_log(
                "notebook_morphology_renderer",
                "render_values_error",
                field_id=self._display_field_id,
                error_type=type(exc).__name__,
                message=str(exc),
                traceback="".join(traceback.format_exception(exc)),
            )
            raise

    def _emit_frame(self, rgba: np.ndarray) -> None:
        buf = io.BytesIO()
        from PIL import Image

        Image.fromarray(rgba[:, :, :3]).save(buf, format="JPEG", quality=70, optimize=False)
        data = buf.getvalue()
        perf_log("notebook_morphology_renderer", "frame_emit", frame_id=self._display_field_id, bytes=len(data), width=int(rgba.shape[1]), height=int(rgba.shape[0]))
        self.emit_update(
            RenderedFrame(
                frame_id=self._display_field_id,
                data=data,
                format="jpeg",
                width=int(rgba.shape[1]),
                height=int(rgba.shape[0]),
            )
        )

    def emit_update(self, payload) -> None:
        self.emit(update_message(payload))


class NotebookLinePlotRenderActor(FrontendBase):
    """Subprocess-capable line renderer for notebook widgets."""

    def __init__(
        self,
        *,
        dt: float = 0.025,
        figsize: tuple[float, float] = (8, 2.5),
    ) -> None:
        super().__init__()
        self._dt = float(dt)
        self._figsize = figsize
        self._fields = {}
        self._line_views = []
        self._last_render = 0.0
        self._render_requested = False
        self._adopted = False

    def initialize(self, app_spec: AppSpec | None) -> None:
        perf_log("notebook_line_plot_renderer", "initialize", has_app_spec=app_spec is not None)
        if app_spec is not None:
            self._adopt_app_spec(app_spec)

    def handle(self, message: Message) -> None:
        payload = message.payload
        if isinstance(payload, AppSpecDeclared):
            perf_log("notebook_line_plot_renderer", "app_spec_declared")
            self._adopt_app_spec(payload.app_spec)
            return
        if isinstance(payload, FieldReplace):
            self._replace_field(payload)
            self._render_requested = True
            return
        if isinstance(payload, FieldAppend):
            self._append_field(payload)
            self._render_requested = True

    def tick(self) -> None:
        if not self._render_requested:
            return
        now = time.monotonic()
        if now - self._last_render < 1.0 / RENDER_HZ:
            return
        self._render_current(force=False)
        self._render_requested = False
        self._last_render = now

    def is_active(self) -> bool:
        return True

    def idle_sleep(self) -> float:
        return 1.0 / 60.0

    def _adopt_app_spec(self, app_spec: AppSpec) -> None:
        if self._adopted:
            return
        self._adopted = True
        from compneurovis.core.views import ViewSpec

        self._fields = {ref.id: field_spec.materialize() for ref, field_spec in app_spec.iter_field_specs()}
        self._line_views = [
            view
            for _, view in app_spec.iter_view_specs()
            if isinstance(view, ViewSpec) and view.kind == "line_plot"
        ]
        perf_log(
            "notebook_line_plot_renderer",
            "adopt_app_spec",
            fields=list(self._fields.keys()),
            line_views=[view.id for view in self._line_views],
        )
        self._render_requested = True
        perf_log("notebook_line_plot_renderer", "initial_fields_ready")

    def _replace_field(self, payload: FieldReplace) -> None:
        field = self._fields.get(payload.field_id)
        if field is None:
            perf_log("notebook_line_plot_renderer", "field_replace_ignored", field_id=payload.field_id, known_fields=list(self._fields.keys()))
            return
        self._fields[payload.field_id] = field.with_values(payload.values, payload.coords, payload.attrs_update)
        perf_log("notebook_line_plot_renderer", "field_replace", field_id=payload.field_id, value_shape=np.asarray(payload.values).shape)

    def _append_field(self, payload: FieldAppend) -> None:
        field = self._fields.get(payload.field_id)
        if field is None:
            perf_log("notebook_line_plot_renderer", "field_append_ignored", field_id=payload.field_id, known_fields=list(self._fields.keys()))
            return
        self._fields[payload.field_id] = field.append(
            payload.append_dim,
            payload.values,
            payload.coord_values,
            max_length=payload.max_length,
            attrs_update=payload.attrs_update,
        )
        perf_log("notebook_line_plot_renderer", "field_append", field_id=payload.field_id, append_dim=payload.append_dim, value_shape=np.asarray(payload.values).shape, coord_count=len(payload.coord_values), max_length=payload.max_length)

    def _render_current(self, *, force: bool) -> None:
        try:
            series = self._collect_line_series()
            if not series and not force:
                perf_log("notebook_line_plot_renderer", "render_skip_no_series", force=force)
                return
            data, width, height = self._render_series(series)
            perf_log(
                "notebook_line_plot_renderer",
                "frame_emit",
                frame_id=LINE_PLOT_FRAME_ID,
                series_count=len(series),
                bytes=len(data),
                width=width,
                height=height,
                dpi=LINE_PLOT_RENDER_DPI,
                quality=LINE_PLOT_JPEG_QUALITY,
            )
            self.emit(update_message(RenderedFrame(LINE_PLOT_FRAME_ID, data, format="jpeg", width=width, height=height)))
        except Exception as exc:
            perf_log(
                "notebook_line_plot_renderer",
                "render_error",
                error_type=type(exc).__name__,
                message=str(exc),
                traceback="".join(traceback.format_exception(exc)),
            )
            raise

    def _collect_line_series(self) -> list[dict[str, Any]]:
        series: list[dict[str, Any]] = []
        for view in self._line_views:
            field = self._fields.get(view.inputs.get("data"))
            if field is None:
                continue
            try:
                series.extend(self._series_for_view(view, field))
            except Exception as exc:
                perf_log("notebook_line_plot_renderer", "skip_view", view_id=view.id, error_type=type(exc).__name__, message=str(exc), traceback="".join(traceback.format_exception(exc)))
        return series

    def _series_for_view(self, view, field) -> list[dict[str, Any]]:
        values = np.asarray(field.values, dtype=np.float32)
        dims = list(field.dims)
        prop_x_dim = view.properties.get("x_dim")
        x_dim = prop_x_dim if prop_x_dim in dims else ("time" if "time" in dims else dims[-1])
        x_axis = dims.index(x_dim)
        prop_series_dim = view.properties.get("series_dim")
        series_dim = prop_series_dim if prop_series_dim in dims else None

        slicers = [slice(None)] * values.ndim
        for axis, dim in enumerate(dims):
            if dim == x_dim or dim == series_dim:
                continue
            slicers[axis] = 0
        values = values[tuple(slicers)]
        kept_dims = [dim for dim, item in zip(dims, slicers) if isinstance(item, slice)]
        x_axis = kept_dims.index(x_dim)
        x = np.asarray(field.coords[x_dim], dtype=np.float32)
        values = np.moveaxis(values, x_axis, -1)

        labels = [str(view.title or view.id)]
        if series_dim is not None and series_dim in kept_dims:
            series_axis = kept_dims.index(series_dim)
            if series_axis > x_axis:
                series_axis -= 1
            values = np.moveaxis(values, series_axis, 0)
            labels = [str(item) for item in field.coords[series_dim]]
        else:
            values = values.reshape(1, values.shape[-1])

        if view.rolling_window is not None and x.size:
            xmin = float(x[-1]) - float(view.rolling_window)
            keep = x >= xmin
            x = x[keep]
            values = values[:, keep]

        def _series(container: Any, label: str, index: int, default: Any):
            if isinstance(container, Mapping):
                return container.get(label, default)
            if container:
                return container[index % len(container)]
            return default

        output = []
        for index, label in enumerate(labels[: values.shape[0]]):
            output.append(
                {
                    "title": str(view.title or view.id),
                    "label": label,
                    "x": x,
                    "y": np.asarray(values[index], dtype=np.float32),
                    "x_label": view.x_label,
                    "y_label": view.y_label,
                    "x_unit": view.x_unit,
                    "y_unit": view.y_unit,
                    "y_min": view.y_min,
                    "y_max": view.y_max,
                    "color": _series(view.colors, label, index, view.color),
                    "linestyle": _series(view.linestyles, label, index, view.linestyle),
                    "linewidth": _series(view.linewidths, label, index, view.linewidth),
                }
            )
        return output

    def _render_series(self, series: list[dict[str, Any]]) -> tuple[bytes, int, int]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from PIL import Image

        groups: dict[str, list[dict[str, Any]]] = {}
        for item in series:
            groups.setdefault(item["title"], []).append(item)
        rows = max(1, len(groups))
        logical_width_in = self._figsize[0]
        logical_height_in = max(self._figsize[1], 2.0 * rows)
        logical_width_px = int(round(logical_width_in * 100))
        logical_height_px = int(round(logical_height_in * 100))
        fig, axes = plt.subplots(
            rows,
            1,
            figsize=(logical_width_in, logical_height_in),
            dpi=LINE_PLOT_RENDER_DPI,
            squeeze=False,
        )
        fig.patch.set_facecolor("#111111")
        palette = ("#4fc3f7", "#ff8c00", "#ff50b4", "#7d3cff", "#00d2be", "#2356b8")
        for ax, (title, items) in zip(axes[:, 0], groups.items()):
            ax.set_facecolor("#111111")
            for spine in ax.spines.values():
                spine.set_color("#555555")
            ax.tick_params(colors="white", labelsize=8)
            ax.set_title(title, color="white", fontsize=10)
            for index, item in enumerate(items):
                color = item.get("color") or palette[index % len(palette)]
                ax.plot(item["x"], item["y"], color=color, lw=1.1, label=item["label"])
            x_label = items[0]["x_label"] + (f" ({items[0]['x_unit']})" if items[0]["x_unit"] else "")
            y_label = items[0]["y_label"] + (f" ({items[0]['y_unit']})" if items[0]["y_unit"] else "")
            ax.set_xlabel(x_label, color="white", fontsize=8)
            ax.set_ylabel(y_label, color="white", fontsize=8)
            if items[0]["y_min"] is not None or items[0]["y_max"] is not None:
                ax.set_ylim(items[0]["y_min"], items[0]["y_max"])
            if len(items) > 1:
                legend = ax.legend(loc="upper right", fontsize=7)
                legend.get_frame().set_alpha(0.25)
        fig.tight_layout(pad=0.45)
        buf = io.BytesIO()
        fig.canvas.draw()
        rgb = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
        plt.close(fig)
        Image.fromarray(rgb).save(
            buf,
            format="JPEG",
            quality=LINE_PLOT_JPEG_QUALITY,
            optimize=False,
            subsampling=0,
        )
        return buf.getvalue(), logical_width_px, logical_height_px


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
        line_plot_figsize: tuple[float, float] = (8, 2.5),
        ylim: tuple[float, float] = (-90.0, 60.0),
        y_label: str = "V (mV)",
        external_morphology_render: bool = False,
        external_line_plot_render: bool = False,
    ) -> None:
        super().__init__(channel=channel)
        self._runtime = runtime
        self._frontend_kwargs = dict(
            dt=dt,
            segment_index=segment_index,
            morph_size=morph_size,
            line_plot_figsize=line_plot_figsize,
            ylim=ylim,
            y_label=y_label,
            external_morphology_render=external_morphology_render,
            external_line_plot_render=external_line_plot_render,
        )
        self._running = False
        self._stopped = False
        self._app_handle = None
        self._task: asyncio.Task | None = None

    def bind_app_handle(self, handle) -> None:
        self._app_handle = handle

    def start(self) -> None:
        def actor_source():
            return NotebookFrontend(**self._frontend_kwargs)

        super().start(actor_source, self._runtime.app_spec)
        self._running = True

    def run(self) -> Any:
        """Kick off asyncio poll loop and return the VBox widget."""
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._poll_loop())
        return self._notebook_frontend()._widget

    def stop(self) -> None:
        if self._stopped:
            return
        if self._app_handle is not None and not getattr(self._app_handle, "_stopping", False):
            self._app_handle.stop()
            return
        self._stopped = True
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
                self.channel.send(
                    make_message(
                        "command",
                        RoutedMessage("line_plot_renderer", command_message(StopActor())),
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
                self.stop()
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
        perf_log("notebook_frontend", "poll_loop_start")
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
                    perf_log("notebook_frontend", "poll_loop_slow", receive_ms=round(recv_ms, 3), flush_renders_ms=round(flush_ms, 3), send_ms=round((td - tc) * 1000, 3))
            except (BrokenPipeError, OSError):
                perf_log("notebook_frontend", "poll_loop_transport_closed")
                self._running = False
                break
            except Exception as exc:
                perf_log(
                    "notebook_frontend",
                    "poll_loop_error",
                    error_type=type(exc).__name__,
                    message=str(exc),
                    traceback="".join(traceback.format_exception(exc)),
                )
                self._running = False
                break
            ticks += 1
            if ticks % 30 == 0:
                perf_log("notebook_frontend", "poll_loop_alive", ticks=ticks)
            await asyncio.sleep(interval)
        perf_log("notebook_frontend", "poll_loop_end", running=self._running)

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
    from compneurovis.core.runtime.actor_launchers import ActorProcess, ThreadActorLauncher, assert_spawn_picklable
    from compneurovis.core.runtime.run import start_app
    from compneurovis.core.runtime.bus import bus_transport
    from compneurovis.core.run_spec import MessageMatch, RouteSpec, RoutingSpec

    routes: list[RouteSpec] = []
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
