"""Generic field-retention resolution for compartment runtimes."""

from __future__ import annotations

import math
import numpy as np

from compneurovis.core.app_spec import AppSpec
from compneurovis.core.messages import FieldReplace


class CompartmentHistoryMixin:
    """Shared selected-entity history state for compartment backends."""

    def _history_structure_changed(self) -> None:
        invalidate = getattr(self, "_invalidate_series_sampler", None)
        if callable(invalidate):
            invalidate()

    def _initialize_series_history(
        self, time_value: float, display_values: np.ndarray
    ) -> None:
        self._last_time_value = float(time_value)
        self._last_display_values = np.asarray(display_values, dtype=np.float32)
        self._last_voltage_values = self._last_display_values
        self._series_history_times = [float(time_value)]
        self._series_history_values_by_id = {}
        self._history_structure_changed()
        capture_mode = getattr(
            self.history_capture_mode, "value", self.history_capture_mode
        )
        if capture_mode == "full":
            self._series_segment_ids = list(self.geometry.entity_ids)
            for entity_id in self._series_segment_ids:
                index = self._entity_index_by_id[entity_id]
                self._series_history_values_by_id[entity_id] = [
                    float(self._last_display_values[index])
                ]
        else:
            self._series_segment_ids = []
            for entity_id in self._preferred_series_entity_ids():
                self._capture_series_entity(entity_id, include_current_sample=True)

    def _clear_series_history(self) -> None:
        self._series_segment_ids = []
        self._series_history_times = []
        self._series_history_values_by_id = {}
        self._history_structure_changed()

    def _capture_series_entity(
        self, entity_id: str, *, include_current_sample: bool
    ) -> bool:
        if entity_id in self._series_history_values_by_id:
            return False
        index = self._entity_index_by_id.get(entity_id)
        if index is None:
            return False
        history = [math.nan] * len(self._series_history_times)
        if include_current_sample and history and self._last_display_values is not None:
            history[-1] = float(self._last_display_values[index])
        self._series_segment_ids.append(entity_id)
        self._series_history_values_by_id[entity_id] = history
        self._history_structure_changed()
        return True

    def _series_field_snapshot(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        times = np.asarray(self._series_history_times, dtype=np.float32)
        entity_ids = np.asarray(self._series_segment_ids)
        if not self._series_segment_ids:
            values = np.empty((0, len(self._series_history_times)), dtype=np.float32)
        else:
            values = np.asarray(
                [
                    self._series_history_values_by_id[entity_id]
                    for entity_id in self._series_segment_ids
                ],
                dtype=np.float32,
            )
        return entity_ids, times, values

    def _series_field_replace(self) -> FieldReplace:
        entity_ids, times, values = self._series_field_snapshot()
        return FieldReplace(
            field_id=self.history_field_id(),
            values=values,
            coords={"segment": entity_ids, "time": times},
        )

    def _display_field_replace(self, display_values: np.ndarray) -> FieldReplace:
        return FieldReplace(
            field_id=self.display_field_id(),
            values=np.asarray(display_values, dtype=np.float32),
        )

    def _trim_selected_series_history(self, max_length: int) -> None:
        if max_length < 0 or len(self._series_history_times) <= max_length:
            return
        self._series_history_times = self._series_history_times[-max_length:]
        for entity_id in tuple(self._series_history_values_by_id):
            self._series_history_values_by_id[entity_id] = (
                self._series_history_values_by_id[entity_id][-max_length:]
            )

    def _append_selected_series_history(
        self, batch_values: np.ndarray, times: list[float]
    ) -> None:
        if not self._series_segment_ids:
            return
        indices = [
            self._entity_index_by_id[entity_id]
            for entity_id in self._series_segment_ids
        ]
        self._append_selected_series_history_values(batch_values[indices, :], times)

    def _append_selected_series_history_values(
        self, values: np.ndarray, times: list[float]
    ) -> None:
        if not self._series_segment_ids:
            return
        self._series_history_times.extend(float(time_value) for time_value in times)
        for row_index, entity_id in enumerate(self._series_segment_ids):
            self._series_history_values_by_id[entity_id].extend(
                float(value) for value in values[row_index]
            )
        max_length = self._field_max_samples.get(self.history_field_id())
        if max_length is not None:
            self._trim_selected_series_history(int(max_length))


def resolved_field_max_samples(
    app_spec: AppSpec | None,
    *,
    field_id: str,
    append_dim: str,
    default: int,
    step: float,
) -> int:
    """Resolve producer capacity from canonical field requirements."""
    required = int(default)
    if app_spec is None:
        return required
    field_spec = app_spec.data.fields.get(field_id)
    if field_spec is None:
        return required
    for retention in field_spec.retention:
        if retention.append_dim != append_dim:
            continue
        if retention.min_samples is not None:
            required = max(required, int(retention.min_samples))
        if retention.min_duration is not None and step > 0:
            required = max(
                required,
                int(math.ceil(float(retention.min_duration) / float(step))) + 1,
            )
    return required
