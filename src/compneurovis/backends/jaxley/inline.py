from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from compneurovis.backends.jaxley.backend import (
    DISPLAY_FIELD_ID as JAXLEY_DISPLAY_FIELD_ID,
    HISTORY_FIELD_ID as JAXLEY_HISTORY_FIELD_ID,
    JaxleyBackend,
)
from compneurovis.core.controls import ControlPresentationSpec, ControlValueSpec
from compneurovis.core.values import ValueBindingSpec
from compneurovis.backends.interaction import SELECTED_ENTITY_IDS_KEY
from compneurovis.inline.bindings import (
    ControlBinding,
    ControlHandle,
    FieldSource,
    MorphologyHandle,
    SelectionRef,
)
from compneurovis.inline.sources import InlineSourceBase


@dataclass
class JaxleyControlBinding(ControlBinding):
    refresh_externals: bool = False
    refresh_params: bool = False

    def apply(self, backend: JaxleyBackend, value: Any) -> bool:
        if self.set is not None:
            self.set(backend._interaction_context(), value)
        if self.refresh_externals:
            backend.refresh_runtime_externals()
            backend._step_index = 0
        if self.refresh_params:
            backend.refresh_runtime_parameters(preserve_state=True)
        return True


class JaxleyInlineSource(InlineSourceBase):
    """Jaxley source-level authoring vocabulary.

    Backend owns Jaxley stepping and sampling. This layer only declares opt-in
    panels/controls over the backend's fields.
    """

    DISPLAY_FIELD_ID = JAXLEY_DISPLAY_FIELD_ID
    HISTORY_FIELD_ID = JAXLEY_HISTORY_FIELD_ID

    def __init__(self, *, title: str = "CompNeuroVis") -> None:
        super().__init__(title=title)
        self._morphology_count = 0

    def morphology(
        self,
        *,
        color_field_id: str | None = None,
        color_map: str = "scalar",
        color_limits: tuple[float, float] | None = (-80.0, 50.0),
        color_norm: str = "auto",
        selectable: bool = True,
    ) -> MorphologyHandle:
        view_id = f"morphology_{self._morphology_count}"
        panel_id = f"morphology-panel-{self._morphology_count}"
        self._morphology_count += 1
        resolved_color_field_id = color_field_id or self.DISPLAY_FIELD_ID
        self._add_morphology_widget(
            view_id=view_id,
            panel_id=panel_id,
            title="Morphology",
            geometry_id=lambda backend: backend.geometry.id,
            color_field_id=resolved_color_field_id,
            entity_dim="segment",
            sample_dim=None,
            selectable=selectable,
            style={
                "color_map": color_map,
                "color_limits": color_limits,
                "color_norm": color_norm,
            },
        )
        return MorphologyHandle(
            id=panel_id,
            selection=FieldSource(
                field_id=self.HISTORY_FIELD_ID,
                series_dim="segment",
                selectors={"segment": ValueBindingSpec(SELECTED_ENTITY_IDS_KEY)},
                unit="mV",
            ),
            selected=SelectionRef(SELECTED_ENTITY_IDS_KEY),
        )

    def control(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], Any] | None = None,
        set: Callable[[Any, Any], None] | None = None,
        min: float = 0.0,
        max: float = 1.0,
        default: Any = 0.0,
        value_spec: ControlValueSpec | None = None,
        presentation: ControlPresentationSpec | None = None,
        send_to_backend: bool | None = None,
        refresh_externals: bool = False,
        refresh_params: bool = False,
    ) -> ControlHandle:
        binding = JaxleyControlBinding(
            name=name,
            label=label,
            get=get,
            set=set,
            min=min,
            max=max,
            default=default,
            value_spec=value_spec,
            presentation=presentation,
            send_to_backend=send_to_backend,
            refresh_externals=refresh_externals,
            refresh_params=refresh_params,
        )
        self._add_control(binding)
        return ControlHandle(binding)

    def _compose_app_spec_for_backend(self, backend: JaxleyBackend):
        return self._compose_startup_data_app_spec_for_backend(
            backend,
            expected_backend_type=JaxleyBackend,
            history_field_id=self.HISTORY_FIELD_ID,
        )


__all__ = [
    "JaxleyControlBinding",
    "JaxleyInlineSource",
    "MorphologyHandle",
]
