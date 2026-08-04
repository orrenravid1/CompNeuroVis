"""Third-party line-plot renderer, registered at *module import*.

This is the correct place for a third-party renderer registration -- the same
place the built-ins use (``_register_builtin_renderers`` runs at import of
``compneurovis.frontends.vispy.extension_renderers``). Importing this module
registers the ``"line_plot_clone"`` kind exactly once per process; when the
actor architecture re-runs the authoring script, ``import`` resolves this from
``sys.modules`` cache and does not re-register. Registering in the authoring
script's top level instead would fire on every re-run and self-collide.

A real third party would ship this as a package module (optionally exposed via a
``compneurovis.vispy_extensions`` entry point, loaded once by the frontend).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compneurovis.core.views import LinePlotViewSpec
from compneurovis.frontends.vispy.extension_renderers import register_extension_renderer
from compneurovis.frontends.vispy.panels.line_plot import LinePlotHostPanel


class LinePlotExtensionHost(LinePlotHostPanel):
    """Adapt the built-in line-plot host to the extension refresh contract."""

    def refresh(
        self,
        view,
        inputs: Mapping[str, Any],
        properties: Mapping[str, Any],
        values: Mapping[str, Any] | None = None,
    ) -> None:
        style = dict(properties)
        line_view = LinePlotViewSpec(
            id=view.id,
            title=view.title,
            field_id=view.inputs.get("data", ""),
            x_dim=style.pop("x_dim", "time"),
            series_dim=style.pop("series_dim", "series"),
            **style,
        )
        super().refresh(line_view, inputs.get("data"), {})


register_extension_renderer("line_plot_clone", LinePlotExtensionHost)
