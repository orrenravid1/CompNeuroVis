from __future__ import annotations

from typing import Any

from compneurovis.backends.jaxley.backend import (
    DISPLAY_FIELD_ID as JAXLEY_DISPLAY_FIELD_ID,
    HISTORY_FIELD_ID as JAXLEY_HISTORY_FIELD_ID,
    JaxleyBackend,
)
from compneurovis.core.values import ValueBindingSpec
from compneurovis.inline.refs import (
    DataRef,
    GeometryRef,
    MorphologyRef,
)
from compneurovis.inline.sources import InlineSourceBase
from compneurovis.components.morphology.authoring import (
    DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY,
    DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY,
    DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY,
)


class JaxleyInlineSource(InlineSourceBase):
    """Jaxley source-level authoring vocabulary.

    Backend owns Jaxley stepping and sampling. This layer only declares opt-in
    panels/controls over the backend's fields.
    """

    DISPLAY_FIELD_ID = JAXLEY_DISPLAY_FIELD_ID
    HISTORY_FIELD_ID = JAXLEY_HISTORY_FIELD_ID

    def morphology(
        self,
        *,
        name: str = "Morphology",
        color_field_id: str | None = None,
        unit: str | None = None,
        color_map: str = "scalar",
        color_limits: tuple[float, float] | None = (-80.0, 50.0),
        color_norm: str = "auto",
        background_color: Any = "white",
        max_refresh_hz: float | None = None,
        camera_orbit_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY,
        camera_pan_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY,
        camera_zoom_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY,
        selected: Any = None,
        selectable: bool = True,
        select_multiple: bool = False,
        panel: bool = True,
    ) -> MorphologyRef:
        """Add an opt-in morphology panel for this Jaxley model.

        Args:
            name: User-facing panel title.
            color_field_id: Advanced identifier for an alternate backend color
                source. The default displays membrane voltage.
            unit: Unit of the displayed values.
            color_map: Registered color-map name.
            color_limits: Fixed `(minimum, maximum)` color range.
            color_norm: Color normalization mode.
            background_color: Canvas background color.
            max_refresh_hz: Maximum morphology repaint rate.
            camera_orbit_sensitivity: Morphology camera rotation multiplier.
            camera_pan_sensitivity: Morphology camera translation multiplier.
            camera_zoom_sensitivity: Morphology camera zoom multiplier.
            selected: Initial segment id, or an iterable when
                `select_multiple=True`.
            selectable: Whether pointer clicks change selection.
            select_multiple: Whether more than one segment can be selected.
            panel: Whether to create the visible 3D panel.

        Returns:
            A morphology handle. Pass `handle.selection` to `line()` for
            optimized selected-segment voltage history; use
            `handle.selected` with context value methods.
        """
        if select_multiple and not selectable:
            raise ValueError("morphology(select_multiple=True) requires selectable=True")

        resolved_color_field_id = color_field_id or self.DISPLAY_FIELD_ID
        morphology = super().morphology(
            GeometryRef("morphology", "morphology"),
            name=name,
            color=DataRef(_field_id=resolved_color_field_id),
            selected=selected,
            select_multiple=select_multiple,
            selectable=selectable,
            panel=panel,
            color_map=color_map,
            color_limits=color_limits,
            color_norm=color_norm,
            background_color=background_color,
            max_refresh_hz=max_refresh_hz,
            camera_orbit_sensitivity=camera_orbit_sensitivity,
            camera_pan_sensitivity=camera_pan_sensitivity,
            camera_zoom_sensitivity=camera_zoom_sensitivity,
        )
        return MorphologyRef(
            id=morphology.id,
            geometry=morphology.geometry,
            color=morphology.color,
            selection=DataRef(
                _field_id=self.HISTORY_FIELD_ID,
                _series_dim="segment",
                _selectors={"segment": ValueBindingSpec(morphology.selected.id)},
                _unit=unit or "mV",
            ),
            selected=morphology.selected,
            entity_click=morphology.entity_click,
        )

    def _compose_app_spec_for_backend(self, backend: JaxleyBackend):
        return self._compose_startup_data_app_spec_for_backend(
            backend,
            expected_backend_type=JaxleyBackend,
            history_field_id=self.HISTORY_FIELD_ID,
        )


__all__ = [
    "JaxleyInlineSource",
    "MorphologyRef",
]




