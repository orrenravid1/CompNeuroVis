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
    CameraCommand,
    FieldReplace,
    Message,
    RenderedFrame,
    RoutedMessage,
    StopActor,
    command_message,
    make_message,
    update_message,
)
from compneurovis.core.runtime import AppRuntime
from compneurovis.frontends.base import FrontendBase
from compneurovis.core.actor_host import ActorHost

POLL_HZ = 30
MAX_SAMPLES = 4000
RENDER_HZ = 15
REMOTE_MORPHOLOGY_FRAME_HZ = 10


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
        trace_figsize: tuple[float, float] = (8, 2.5),
        ylim: tuple[float, float] = (-90.0, 60.0),
        y_label: str = "V (mV)",
        external_morphology_render: bool = False,
    ) -> None:
        super().__init__()
        self._dt = dt
        self._segment_index = segment_index
        self._display_field_id = "segment_display"
        self._voltages: np.ndarray | None = None
        self._buf: list[float] = []
        self._step = 0
        self._last_render = 0.0
        self._render_due = False
        self._morph_dirty = False
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
        self._morph_widget = widgets.Image(format="png", width=morph_size[0], height=morph_size[1])

        # Mouse state for drag-to-rotate
        self._mouse_down = False
        self._mouse_last: tuple[int, int] = (0, 0)

        from ipyevents import Event
        morph_events = Event(
            source=self._morph_widget,
            watched_events=["mousedown", "mouseup", "mousemove", "wheel", "mouseleave", "dragstart"],
            prevent_default_action=True,
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

    def initialize(self, app_spec: AppSpec) -> None:
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

        if not self._external_morphology_render:
            self._render_morph()

    def handle(self, message: Message) -> None:
        payload = message.payload
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

    # ---------------------------------------------------------------------- #
    # Rendering (called by host step loop)                                    #
    # ---------------------------------------------------------------------- #

    def flush_renders(self, now: float) -> None:
        """Render morph+trace if timing is due; render morph if camera dirty."""
        if self._trace_interacting and self._trace_resume_at and now >= self._trace_resume_at:
            self._trace_interacting = False
            self._trace_resume_at = 0.0
        if self._render_due and now - self._last_render >= 1.0 / RENDER_HZ:
            if not self._external_morphology_render:
                self._render_morph()
            if self._trace_interacting:
                self._last_render = now
            else:
                self._render_trace()
                self._last_render = now
                self._render_due = False
        if self._morph_dirty and not self._external_morphology_render:
            self._render_morph()
            self._morph_dirty = False

    # ---------------------------------------------------------------------- #

    def _on_mouse_event(self, event: dict) -> None:
        etype = event.get("type")
        x, y = event.get("offsetX", 0), event.get("offsetY", 0)

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
            return
        if self._voltages is not None:
            self._morph_renderer.update_colors(
                self._voltages, self._color_map,
                color_limits=self._color_limits, color_norm=self._color_norm,
            )
        rgba = self._morph_canvas.render()
        buf = io.BytesIO()
        from PIL import Image
        Image.fromarray(rgba).save(buf, format="png")
        self._morph_widget.value = buf.getvalue()

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
        while self._running:
            if frontend.stop_requested:
                self.stop()
                break
            try:
                self.receive()
                frontend.flush_renders(time.monotonic())
                self.flush()
            except (BrokenPipeError, OSError):
                self._running = False
                break
            await asyncio.sleep(interval)

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
    """Start backend thread + notebook frontend and return the VBox widget.

    Compiles to a RunSpec and calls start_app() so the full architecture
    (AppRuntime, ActorSpec, transport) is exercised uniformly.

    Parameters
    ----------
    backend_factory : zero-arg callable returning a BackendBase instance
    app_spec        : AppSpec built from the backend before calling this
    dt              : simulation timestep in ms (for the trace time axis)
    """
    from compneurovis.core.actor_launchers import ThreadActorLauncher
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

    handle = start_app(RunSpec(
        app_spec=app_spec,
        actors=[
            ActorSpec(
                id="backend",
                host_source=lambda r, ch, _f=backend_factory: ThreadActorLauncher(_f, r, ch),
            ),
            ActorSpec(
                id="frontend",
                host_source=lambda r, ch: NotebookActorHost(r, ch, dt=dt),
                runs_in_foreground=False,
            ),
        ],
        transport=bus_transport(mode="inprocess"),
        routing=routing,
    ))
    return handle.widget("frontend")


__all__ = ["NotebookActorHost", "NotebookFrontend", "NotebookMorphologyRenderActor"]
