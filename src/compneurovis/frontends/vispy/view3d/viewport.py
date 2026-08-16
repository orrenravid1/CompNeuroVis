from __future__ import annotations

import time
from typing import Any, Protocol

import numpy as np
from PyQt6 import QtGui, QtWidgets
from vispy import scene
from vispy.scene.cameras import TurntableCamera

from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.app_spec import PanelSpec
from compneurovis.core.clicks import HitValue
from compneurovis.core.pointer import HitRecord, PointerEvent, PointerSample
from compneurovis.frontends.pointer_routing import (
    ClickBinding,
    ClickRecognizer,
    PointerClaim,
    PointerObservationHub,
    PointerRouter,
)


def _camera_sensitivity(value: float, name: str) -> float:
    resolved = float(value)
    if not np.isfinite(resolved) or resolved < 0:
        raise ValueError(f"{name} must be non-negative and finite")
    return resolved


class AdjustableTurntableCamera(TurntableCamera):
    """Turntable camera with independent orbit, pan, and zoom multipliers."""

    def __init__(
        self,
        *args,
        orbit_sensitivity: float = 1.0,
        pan_sensitivity: float = 1.0,
        zoom_sensitivity: float = 1.0,
        **kwargs,
    ) -> None:
        self.orbit_sensitivity = _camera_sensitivity(
            orbit_sensitivity, "camera_orbit_sensitivity"
        )
        self.zoom_sensitivity = _camera_sensitivity(
            zoom_sensitivity, "camera_zoom_sensitivity"
        )
        kwargs["translate_speed"] = _camera_sensitivity(
            pan_sensitivity, "camera_pan_sensitivity"
        )
        super().__init__(*args, **kwargs)
        self.zoom_factor = TurntableCamera.zoom_factor * self.zoom_sensitivity

    def _update_rotation(self, event) -> None:
        p1 = event.mouse_event.press_event.pos
        p2 = event.mouse_event.pos
        if self._event_value is None:
            self._event_value = self.azimuth, self.elevation
        degrees_per_pixel = 0.5 * self.orbit_sensitivity
        self.azimuth = self._event_value[0] - (p2 - p1)[0] * degrees_per_pixel
        self.elevation = self._event_value[1] + (p2 - p1)[1] * degrees_per_pixel

    def viewbox_mouse_event(self, event) -> None:
        if event.handled or not self.interactive:
            return
        if event.type == "mouse_wheel":
            factor = 1.1 ** (-float(event.delta[1]) * self.zoom_sensitivity)
            self._scale_factor *= factor
            if self._distance is not None:
                self._distance *= factor
            self.view_changed()
            event.handled = True
            return
        if event.type == "gesture_zoom":
            factor = max(1e-6, 1.0 - float(event.scale)) ** self.zoom_sensitivity
            self._scale_factor *= factor
            if self._distance is not None:
                self._distance *= factor
            self.view_changed()
            event.handled = True
            return
        super().viewbox_mouse_event(event)


class Viewport3DVisual(Protocol):
    def refresh_for_target(self, kind: str, view: Any, ctx: Any) -> None:
        ...

    def clear(self) -> None:
        ...


class InstrumentedSceneCanvas(scene.SceneCanvas):
    def __init__(self, *args, perf_panel_id: str | None = None, **kwargs):
        self._perf_panel_id = perf_panel_id
        self._perf_draw_count = 0
        super().__init__(*args, **kwargs)

    def on_draw(self, event) -> None:
        started = time.monotonic()
        super().on_draw(event)
        self._perf_draw_count += 1
        if self._perf_draw_count == 1:
            self._log_gl_info()
        perf_log(
            "view_3d",
            "canvas_draw",
            panel_id=self._perf_panel_id,
            draw_count=self._perf_draw_count,
            width_px=int(self.size[0]),
            height_px=int(self.size[1]),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _log_gl_info(self) -> None:
        # One-shot: is this real GPU GL or a software rasterizer (llvmpipe)? A slow
        # draw on a tiny canvas points at software GL or vsync swap-blocking.
        try:
            from vispy.gloo import gl
            info = {
                "renderer": str(gl.glGetParameter(gl.GL_RENDERER)),
                "vendor": str(gl.glGetParameter(gl.GL_VENDOR)),
                "version": str(gl.glGetParameter(gl.GL_VERSION)),
            }
            native_format = getattr(self.native, "format", lambda: None)()
            if native_format is not None:
                info["qt_swap_interval"] = int(native_format.swapInterval())
        except Exception as exc:  # pragma: no cover - diagnostic only
            info = {"error": repr(exc)}
        perf_log("view_3d", "gl_info", panel_id=self._perf_panel_id, **info)


class Viewport3DPanel(QtWidgets.QWidget):
    DRAG_THRESHOLD = 5

    def __init__(
        self,
        *,
        host_spec: PanelSpec | None = None,
        camera: tuple[float | None, float, float] | None = None,
        camera_sensitivity: tuple[float, float, float] | None = None,
        resolve_click=None,
        on_click=None,
        resolve_pointer_interaction=None,
        on_pointer_interaction=None,
        parent=None,
    ):
        super().__init__(parent)
        self._panel_id = host_spec.id if host_spec is not None else None
        self.canvas = InstrumentedSceneCanvas(
            keys="interactive",
            bgcolor="white",
            show=False,
            # vsync off: with vsync on (default), each draw blocks on the display
            # vblank (~tens of ms on Windows/DWM even for a trivial scene), which
            # stalls the Qt UI thread and makes interaction lag. We refresh at a
            # capped rate, so tearing is a non-issue for this data view.
            vsync=False,
            perf_panel_id=self._panel_id,
        )
        self._configure_native_swap_interval()
        self.view = self.canvas.central_widget.add_view()
        # Camera is the 3-D view's, resolved by the caller from the primary view's
        # render-config; the generic fallback is only for a view that declares none.
        distance, elevation, azimuth = camera if camera is not None else (200.0, 30.0, 30.0)
        orbit, pan, zoom = camera_sensitivity or (1.0, 1.0, 1.0)
        self.view.camera = AdjustableTurntableCamera(
            fov=60,
            distance=distance,
            elevation=elevation,
            azimuth=azimuth,
            orbit_sensitivity=orbit,
            pan_sensitivity=pan,
            zoom_sensitivity=zoom,
            up="+z",
        )
        self.resolve_click = resolve_click
        self.on_click = on_click
        self.resolve_pointer_interaction = resolve_pointer_interaction
        self.on_pointer_interaction = on_pointer_interaction
        self._pointer_router = PointerRouter()
        self.pointer_observations = PointerObservationHub(
            self._set_hover_observation_active,
        )
        self._click_recognizer = ClickRecognizer(max_distance=self.DRAG_THRESHOLD)
        self._visuals: dict[str, Viewport3DVisual] = {}
        self._contribution_hit_testers: list[tuple[Any, frozenset[str]]] = []
        self._active_visual_key: str | None = None
        self._active_visual_hittable = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas.native)

        for event_name in ("mouse_press", "mouse_move", "mouse_release"):
            getattr(self.view.events, event_name).connect(
                self._on_pointer_event,
                # Vispy inserts newly connected callbacks first. The camera was
                # connected when assigned to the ViewBox, so this router receives
                # the event first and the camera remains the unhandled fallback.
                position="first",
            )

    def _set_hover_observation_active(self, active: bool) -> None:
        # SceneCanvas intentionally suppresses passive mouse moves by default.
        # Enable its private scene-event switch only while an authored transient
        # presentation observer needs the stream; press/drag routing is unchanged.
        self.canvas._send_hover_events = bool(active)

    def _configure_native_swap_interval(self) -> None:
        native = self.canvas.native
        get_format = getattr(native, "format", None)
        set_format = getattr(native, "setFormat", None)
        if not callable(get_format) or not callable(set_format):
            perf_log(
                "view_3d",
                "canvas_swap_interval_config",
                panel_id=self._panel_id,
                supported=False,
                native_type=type(native).__name__,
            )
            return
        before = get_format()
        fmt = QtGui.QSurfaceFormat(before)
        fmt.setSwapInterval(0)
        set_format(fmt)
        after = get_format()
        perf_log(
            "view_3d",
            "canvas_swap_interval_config",
            panel_id=self._panel_id,
            supported=True,
            native_type=type(native).__name__,
            swap_interval_before=int(before.swapInterval()),
            swap_interval_after=int(after.swapInterval()),
        )

    @property
    def active_visual_key(self) -> str | None:
        return self._active_visual_key

    def mount_visual(self, key: str, visual: Viewport3DVisual) -> None:
        if key in self._visuals:
            raise ValueError(f"3D visual '{key}' is already mounted")
        self._visuals[key] = visual

    def set_contribution_hit_testers(
        self,
        testers: list[tuple[Any, frozenset[str]]],
    ) -> None:
        self._contribution_hit_testers = list(testers)

    def visual(self, key: str) -> Viewport3DVisual:
        try:
            return self._visuals[key]
        except KeyError as exc:
            raise ValueError(f"Unknown 3D visual '{key}'") from exc

    def activate_visual(self, key: str, *, view=None) -> Viewport3DVisual:
        visual = self.visual(key)
        if self._active_visual_key != key:
            self._clear_active_visual()
            self._active_visual_key = key
        # Hit testing is the visual's own capability; semantic click, pointer,
        # selection, and presentation behavior remain independent consumers.
        wants_hit_test = getattr(visual, "wants_hit_test", None)
        self._active_visual_hittable = (
            bool(wants_hit_test(view)) if wants_hit_test is not None else False
        )
        self.canvas.native.setVisible(True)
        return visual

    def clear(self) -> None:
        self._pointer_router.cancel_all(self._dispatch_pointer_claim)
        for visual in self._visuals.values():
            visual.clear()
        self._active_visual_key = None
        self._active_visual_hittable = False
        self.canvas.native.setVisible(False)

    def commit(self) -> None:
        started = time.monotonic()
        self.canvas.update()
        perf_log(
            "view_3d",
            "commit",
            panel_id=self._panel_id,
            active_visual_key=self._active_visual_key,
            width_px=self.width(),
            height_px=self.height(),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _clear_active_visual(self) -> None:
        if self._active_visual_key is None:
            return
        self._visuals[self._active_visual_key].clear()

    def _active_visual(self) -> Viewport3DVisual | None:
        if self._active_visual_key is None:
            return None
        return self._visuals[self._active_visual_key]

    def _on_pointer_event(self, ev) -> None:
        raw_event = getattr(ev, "mouse_event", ev)
        sample = self._pointer_sample(raw_event)
        pointer_observations = self.__dict__.get("pointer_observations")
        if pointer_observations is None:
            pointer_observations = PointerObservationHub()
            self.__dict__["pointer_observations"] = pointer_observations
        captured = self._pointer_router.is_captured(sample.pointer_id)
        # Once an authored interaction captures a pointer, it owns the complete
        # stream through release/cancel. A native/default consumer marking a later
        # move handled cannot revoke that ownership. For uncaptured streams,
        # handled remains the ordinary semantic-routing boundary. Observational
        # presentation still receives the raw stream before that boundary so a
        # hover preview is not gated by camera/default handling.
        needs_hit = (
            sample.phase == "press"
            or captured
            or pointer_observations.needs_hits
        )
        hit = self._hit_at(raw_event.pos) if needs_hit else None
        pointer = PointerEvent(
            sample=sample,
            hits=() if hit is None else (hit,),
        )
        pointer_observations.emit(pointer)
        if ev.handled and not captured:
            return
        claimed = self._pointer_router.route(
            pointer,
            resolve_claim=self._resolve_pointer_claim,
            dispatch=self._dispatch_pointer_claim,
        )
        if claimed:
            self._click_recognizer.cancel(sample.pointer_id)
            ev.handled = True
            return

        click = self._click_recognizer.feed(pointer)
        click_hit = None if click is None or not click.press.hits else click.press.hits[0]
        if click_hit is not None:
            self._dispatch_click(click, click_hit)

        logged_hit = hit or click_hit

        perf_log(
            "view_3d",
            f"pointer_{sample.phase}",
            panel_id=self._panel_id,
            pointer_id=sample.pointer_id,
            pos=[float(value) for value in sample.local_position or sample.position],
            target_role=None if logged_hit is None else logged_hit.target_role,
            primitive_id=None if logged_hit is None else logged_hit.primitive_id,
            claimed=claimed,
        )

    def _hit_at(self, pos) -> HitRecord | None:
        visual = self._active_visual()
        x, y = pos
        _, h = self.canvas.size
        ps = self.canvas.pixel_scale
        xf, yf = int(x * ps), int((h - y - 1) * ps)
        for tester, allowed_roles in self.__dict__.get(
            "_contribution_hit_testers", ()
        ):
            hit = tester.hit_test(xf, yf, self.canvas)
            if hit is None:
                continue
            if hit.target_role not in allowed_roles:
                raise ValueError(
                    f"Visual contribution produced undeclared hit role "
                    f"{hit.target_role!r}"
                )
            return hit
        if visual is None or not self._active_visual_hittable:
            return None
        hit_test = getattr(visual, "hit_test", None)
        return None if not callable(hit_test) else hit_test(xf, yf, self.canvas)

    def _resolve_pointer_claim(self, pointer: PointerEvent) -> PointerClaim | None:
        if (
            self.resolve_pointer_interaction is None
            or self.on_pointer_interaction is None
        ):
            return None
        if pointer.sample.phase != "press" or pointer.sample.button is None:
            return None
        hit = pointer.hits[0] if pointer.hits else None
        if hit is None:
            return None
        claim = self.resolve_pointer_interaction(
            hit.target_role,
            pointer.sample.button,
        )
        return claim

    def _dispatch_pointer_claim(
        self,
        claim: PointerClaim,
        pointer: PointerEvent,
    ) -> None:
        if self.on_pointer_interaction is None:
            return
        hit = pointer.hit_for(claim.target_role)
        value = None if hit is None else self._value_for_hit(hit, claim.result_kind)
        self.on_pointer_interaction(claim.owner, pointer, value)

    def _dispatch_click(self, gesture, hit: HitRecord) -> None:
        visual = self._active_visual()
        if visual is None or self.resolve_click is None or self.on_click is None:
            return
        claim: ClickBinding | None = self.resolve_click(hit.target_role)
        if claim is None:
            return
        value = self._value_for_hit(hit, claim.result_kind)
        self.on_click(claim.owner, gesture, value)

    def _value_for_hit(self, hit: HitRecord, result_kind: str):
        if result_kind == "hit":
            return HitValue.from_record(hit)
        visual = self._active_visual()
        resolver = None if visual is None else getattr(visual, "value_for_hit", None)
        if not callable(resolver):
            visual_name = "None" if visual is None else type(visual).__name__
            raise ValueError(
                f"Visual {visual_name} cannot resolve hit result kind "
                f"{result_kind!r}"
            )
        return resolver(hit, result_kind)

    def _pointer_sample(self, ev) -> PointerSample:
        phase_by_type = {
            "mouse_press": "press",
            "mouse_move": "move",
            "mouse_release": "release",
        }
        try:
            phase = phase_by_type[ev.type]
        except KeyError as exc:
            raise ValueError(f"Unsupported Vispy pointer event type {ev.type!r}") from exc
        width, height = self.canvas.size
        width = max(float(width), 1.0)
        height = max(float(height), 1.0)
        local_position = (float(ev.pos[0]), float(ev.pos[1]))
        previous = getattr(ev, "last_event", None)
        if previous is None:
            local_delta = (0.0, 0.0)
        else:
            local_delta = (
                local_position[0] - float(previous.pos[0]),
                local_position[1] - float(previous.pos[1]),
            )
        pointer_id = getattr(ev, "pointer_id", None)
        native = getattr(ev, "native", None)
        if pointer_id is None and native is not None:
            pointer_id = getattr(native, "pointerId", None)
        pointer_type = getattr(ev, "pointer_type", None)
        if pointer_type is None and native is not None:
            pointer_type = getattr(native, "pointerType", None)
        normalized_type = str(pointer_type or "mouse").lower()
        if normalized_type not in ("mouse", "touch", "pen"):
            normalized_type = "unknown"
        button = self._button_name(getattr(ev, "button", None))
        buttons = tuple(
            value
            for value in (
                self._button_name(item)
                for item in (getattr(ev, "buttons", ()) or ())
            )
            if value is not None
        )
        modifiers = tuple(
            str(getattr(value, "name", value)).lower()
            for value in (getattr(ev, "modifiers", ()) or ())
        )
        pressure = getattr(ev, "pressure", None)
        return PointerSample(
            pointer_id=str(pointer_id if pointer_id is not None else "mouse:0"),
            pointer_type=normalized_type,
            phase=phase,
            position=(local_position[0] / width, local_position[1] / height),
            delta=(local_delta[0] / width, local_delta[1] / height),
            local_position=local_position,
            local_delta=local_delta,
            button=button,
            buttons=buttons,
            modifiers=modifiers,
            timestamp=getattr(ev, "time", None),
            pressure=pressure,
        )

    @staticmethod
    def _button_name(button) -> str | None:
        if button in (1, "left", "primary"):
            return "primary"
        if button in (2, "right", "secondary"):
            return "secondary"
        if button in (3, "middle"):
            return "middle"
        return None
