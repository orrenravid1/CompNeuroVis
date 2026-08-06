"""Notebook jupyter_rfb host using asyncio.

Runs the backend in a daemon thread (JAX/NEURON release the GIL so XLA/C++
compute runs in parallel). Polls an in-process queue transport from an asyncio
coroutine and pushes updates to a VisPy SceneCanvas rendered via jupyter_rfb.

Usage (in a notebook cell)::

    import vispy
    vispy.use("jupyter_rfb")          # must be before any vispy scene import

    from compneurovis.frontends.vispy.notebook_host_jupyterlab import NotebookRfbHost
    host = NotebookRfbHost(app_spec, channel)
    host.start()                      # returns the ipywidget; display it
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import numpy as np

from compneurovis.core.app_spec import AppSpec
from compneurovis.inline.widgets.morphology_geometry import (
    morphology_geometry_from_spec,
)
from compneurovis.core.messages import FieldAppend, FieldReplace, Message, MessagePayload
from compneurovis.frontends.vispy.render_config import view_render_config
from compneurovis.frontends.vispy.view3d.morphology import MorphologyViewSpec
from compneurovis.core.channel import Channel


POLL_HZ = 30


class NotebookRfbHost:
    """Asyncio-driven jupyter_rfb widget host. No Qt required."""

    def __init__(self, app_spec: AppSpec, channel: Channel) -> None:
        self._channel = channel
        self._running = False
        self._task: asyncio.Task | None = None

        # VisPy canvas — jupyter_rfb must already be set as vispy backend
        from vispy import scene
        from vispy.scene.cameras import TurntableCamera

        self._canvas = scene.SceneCanvas(
            keys="interactive",
            bgcolor="black",
            show=True,
            size=(800, 600),
        )
        view = self._canvas.central_widget.add_view()
        view.camera = TurntableCamera(
            fov=60, distance=200, elevation=30, azimuth=30,
            translate_speed=100, up="+z",
        )

        from compneurovis.frontends.vispy.renderers.morphology import MorphologyRenderer
        self._renderer = MorphologyRenderer(view)

        # Resolve display field and view settings from AppSpec
        self._display_field_id: str | None = None
        self._color_map = "scalar"
        self._color_limits: tuple[float, float] | None = (-80.0, 50.0)
        self._color_norm = "auto"

        self._init_from_app_spec(app_spec)

    # ------------------------------------------------------------------
    def _init_from_app_spec(self, app_spec: AppSpec) -> None:
        # GeometrySpec
        for spec in app_spec.data.geometries.values():
            geo = morphology_geometry_from_spec(spec)
            if geo is not None:
                self._renderer.set_geometry(geo)
                break

        # View spec → color settings
        for raw_view in app_spec.view_catalog.views.values():
            view_spec = view_render_config(raw_view)
            if isinstance(view_spec, MorphologyViewSpec):
                self._display_field_id = view_spec.color_field_id
                self._color_map = view_spec.color_map or "scalar"
                self._color_norm = view_spec.color_norm or "auto"
                if view_spec.color_limits is not None and not isinstance(view_spec.color_limits, str):
                    self._color_limits = tuple(view_spec.color_limits)  # type: ignore[assignment]
                break

        # Initial colors from field in AppSpec
        if self._display_field_id:
            field = app_spec.data.fields.get(self._display_field_id)
            if field is not None and field.initial_values is not None:
                values = np.asarray(field.initial_values, dtype=np.float32)
                if values.ndim > 1:
                    values = values[:, -1]
                self._renderer.update_colors(
                    values, self._color_map,
                    color_limits=self._color_limits,
                    color_norm=self._color_norm,
                )

    # ------------------------------------------------------------------
    def _handle(self, msg: Message[MessagePayload]) -> None:
        payload = msg.payload
        if isinstance(payload, FieldReplace):
            if payload.field_id == self._display_field_id:
                values = np.asarray(payload.values, dtype=np.float32)
                if values.ndim > 1:
                    values = values[:, -1]
                self._renderer.update_colors(
                    values, self._color_map,
                    color_limits=self._color_limits,
                    color_norm=self._color_norm,
                )
                self._canvas.update()
        elif isinstance(payload, FieldAppend):
            if payload.field_id == self._display_field_id:
                values = np.asarray(payload.values, dtype=np.float32)
                if values.ndim > 1:
                    values = values[:, -1]
                self._renderer.update_colors(
                    values, self._color_map,
                    color_limits=self._color_limits,
                    color_norm=self._color_norm,
                )
                self._canvas.update()

    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        interval = 1.0 / POLL_HZ
        while self._running:
            try:
                for msg in self._channel.poll():
                    self._handle(msg)
            except (BrokenPipeError, OSError):
                self._running = False
                break
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    def start(self) -> Any:
        """Start asyncio polling and return the jupyter_rfb widget."""
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._poll_loop())
        return self._canvas.native

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None


# ---------------------------------------------------------------------------
# Convenience: run actor in a daemon thread + return notebook widget
# ---------------------------------------------------------------------------

def run_notebook_actor_thread(actor_host) -> None:
    """Target for the daemon thread that drives an ActorHost."""
    try:
        while not actor_host.should_stop():
            started = time.monotonic()
            actor_host.step()
            remaining = actor_host.idle_sleep() - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
    except (BrokenPipeError, OSError):
        pass
    finally:
        actor_host.stop()


def _launch_notebook(
    *,
    backend_factory,
    app_spec: AppSpec,
    frontend_channel: Channel,
    backend_channel: Channel,
) -> Any:
    """Start backend thread and notebook frontend, return the widget.

    Parameters
    ----------
    backend_factory:
        Zero-arg callable returning a backend instance.
    app_spec:
        AppSpec built from the backend before calling this.
    frontend_channel / backend_channel:
        The two sides of a make_inprocess_pair().
    """
    from compneurovis.core.actor_host import ActorHost

    host = ActorHost(channel=backend_channel)
    host.start(backend_factory, app_spec)

    t = threading.Thread(target=run_notebook_actor_thread, args=(host,), daemon=True)
    t.start()

    nb_host = NotebookRfbHost(app_spec, frontend_channel)
    return nb_host.start()


__all__ = ["NotebookRfbHost", "run_notebook_actor_thread"]
