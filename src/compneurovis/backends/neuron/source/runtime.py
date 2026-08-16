"""Source-aware NEURON runtime preserving native pointer-vector collection."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from compneurovis.backends import HistoryCaptureMode
from compneurovis.backends.compartment import resolved_field_max_samples
from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.backends.neuron.source.declarations import (
    ClickHandler,
    DerivedField,
    LineRecorder,
)
from compneurovis.backends.neuron.source.recording import (
    SegmentVariableDisplayBinding,
    SegmentVariableHistoryBinding,
    _recorder_sample_indices,
    _state_value,
)
from compneurovis.core.messages import (
    FieldAppend,
    FieldReplace,
    Message,
    MessagePayload,
    Reset,
    ValueChange,
)
from compneurovis.core.runtime.performance import perf_log
from compneurovis.inline.backend import SourceBackendMixin
from compneurovis.inline.data_producers import SeriesProducer, SnapshotProducer
from compneurovis.inline.interactions import (
    ActionInteraction,
    ControlInteraction,
    ClickHandlerBinding,
    PointerInteractionHandlerBinding,
)

@dataclass
class _SourceStep:
    display_values: np.ndarray | None
    selected_series_values: np.ndarray | None
    segment_variable_values: tuple[np.ndarray, ...]
    segment_variable_generations: tuple[int, ...]
    recorder_values: tuple[np.ndarray, ...]


class SourceBackend(SourceBackendMixin, NeuronBackend):
    def __init__(
        self,
        *,
        sections: list,
        controls: list[ControlInteraction],
        actions: list[ActionInteraction],
        series: list[SeriesProducer],
        fields: list[SnapshotProducer],
        segment_variable_displays: list[SegmentVariableDisplayBinding],
        segment_variable_histories: list[SegmentVariableHistoryBinding],
        recorders: list[LineRecorder],
        click_handlers: list[ClickHandlerBinding],
        pointer_handlers: list[PointerInteractionHandlerBinding],
        capture_predicate: ClickHandler | None,
        initial_state: list[tuple[str, Any]],
        derives: list[DerivedField],
        step_fn: Callable[[], None] | None,
        dt: float,
        display_dt: float | None,
        flush_dt: float | None,
        v_init: float,
        title: str,
    ) -> None:
        super().__init__(
            dt=dt,
            v_init=v_init,
            title=title,
            display_dt=display_dt,
            segment_sampling=None,
            geometry_required=bool(
                segment_variable_displays or segment_variable_histories
            ),
        )
        self._provided_sections = sections
        self._init_source_bindings(
            controls=controls,
            actions=actions,
            series=series,
            fields=fields,
            click_handlers=click_handlers,
            pointer_interaction_handlers=pointer_handlers,
        )
        self._segment_variable_displays = segment_variable_displays
        self._segment_variable_histories = segment_variable_histories
        self._selection_history_bindings: dict[
            str, tuple[SegmentVariableHistoryBinding, ...]
        ] = {
            selection_id: tuple(
                binding
                for binding in self._segment_variable_histories
                if binding.selection_id == selection_id
            )
            for selection_id in {
                binding.selection_id
                for binding in self._segment_variable_histories
            }
        }
        self._selection_generations = {
            selection_id: 0 for selection_id in self._selection_history_bindings
        }
        for binding in self._segment_variable_displays:
            self._bind_segment_variable_display(binding)
        self._recorders = recorders
        self._capture_predicate = capture_predicate
        self._initial_state_seeds = initial_state
        self._derives = derives
        self._custom_step_fn = step_fn
        # Coalesce emission every `flush_dt` sim-ms (0 = every tick). The buffering
        # itself lives on the base backend; the source only sets the interval.
        self._flush_dt = float(flush_dt) if flush_dt else 0.0

    def build_sections(self) -> list:
        return self._provided_sections


    def _bind_segment_variable_display(self, binding: SegmentVariableDisplayBinding) -> None:
        binding._bind_state_updates(
            lambda _binding=binding: self._apply_segment_variable_display(
                _binding
            )
        )

    def _apply_segment_variable_display(
        self, binding: SegmentVariableDisplayBinding
    ) -> None:
        """Commit one retarget: values, palette, limits and unit in one message."""

        started = time.monotonic()
        for history in self._segment_variable_histories:
            if history.display_binding is binding:
                self._selection_generations[history.selection_id] = (
                    self._selection_generations.get(history.selection_id, 0) + 1
                )
        self.emit_update(binding._replace_payload(self))
        for history in self._segment_variable_histories:
            if history.display_binding is binding:
                self.emit_update(history._replace_payload(self))
        perf_log(
            "neuron_morphology_display",
            "retarget",
            variable=binding.variable,
            source=self._display_source_kind(binding),
            color_map=binding.color_map,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    @staticmethod
    def _display_source_kind(binding: SegmentVariableDisplayBinding) -> str:
        if isinstance(binding.source, str):
            return f"neuron:{binding.source}"
        if callable(binding.source):
            return "callable"
        return "explicit-values"

    def initialize(self, app_spec) -> None:
        retained_producers = [
            *self._segment_variable_histories,
            *self._recorders,
            *self._source_series,
            *(derived for derived in self._derives if derived.mode == "append"),
        ]
        for producer in retained_producers:
            field_id = getattr(
                producer,
                "_field_id",
                getattr(producer, "field_id", None),
            )
            if field_id:
                producer.max_samples = resolved_field_max_samples(
                    app_spec,
                    field_id=field_id,
                    append_dim="time",
                    default=producer.max_samples,
                    step=self.dt,
                )
        # Base initialize handles the no-display case (it only seeds a selected
        # entity when there is geometry), so no display-specific branch here.
        super().initialize(app_spec)
        self._emit_segment_variable_replaces()
        updates: dict[str, Any] = {}
        for key, value in self._initial_state_seeds:
            resolved = value(self._interaction_context()) if callable(value) else value
            self.values.set(key, resolved)
            updates[key] = resolved
        if updates:
            self.emit_update(ValueChange(updates))

    def should_capture_series_on_click(self, entity_id: str, context) -> bool:
        if self._capture_predicate is None:
            return True
        return bool(self._capture_predicate(context, entity_id))

    def _reset_backend_field_history(self, field_ids: set | None) -> None:
        super()._reset_backend_field_history(field_ids)
        for recorder in self._recorders:
            if field_ids is None or recorder.field_id in field_ids:
                self.emit_update(recorder.replace_payload())
        for binding in self._segment_variable_histories:
            if field_ids is None or binding._field_id in field_ids:
                self.emit_update(binding._replace_payload(self))

    def _uses_source_step(self) -> bool:
        return bool(self._segment_variable_histories or self._recorders)

    def _sample_source_step(self, *, include_display_values: bool) -> Any:
        display_values = (
            self._read_display_values()
            if include_display_values and self._segment_sampling is not None
            else None
        )
        selected_series_values = None
        if (
            not include_display_values
            and self._segment_sampling is not None
            and self._series_segment_ids
        ):
            selected_series_values = self._read_selected_series_values()
        if include_display_values and not self._uses_source_step():
            return display_values
        return _SourceStep(
            display_values=display_values,
            selected_series_values=selected_series_values,
            segment_variable_values=tuple(
                binding._sample_selected(self) for binding in self._segment_variable_histories
            ),
            segment_variable_generations=tuple(
                self._selection_generations.get(binding.selection_id, 0)
                for binding in self._segment_variable_histories
            ),
            recorder_values=tuple(recorder.sample_vector() for recorder in self._recorders),
        )

    def _advance(self) -> None:
        if self._custom_step_fn is None:
            from neuron import h
            h.fadvance()
        else:
            self._custom_step_fn()

    def _on_step(self, t: float) -> None:
        self._observe_derives(t)

    def _sample_step(self) -> Any:
        include_display = (
            self.history_capture_mode == HistoryCaptureMode.FULL
            and self._segment_sampling is not None
        )
        return self._sample_source_step(include_display_values=include_display)

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        if steps and isinstance(steps[0], _SourceStep):
            if steps[0].display_values is None:
                selected_series_values = None
                if self._segment_sampling is not None and self._series_segment_ids:
                    selected_series_values = np.stack(
                        [step.selected_series_values for step in steps],
                        axis=1,
                    ).astype(np.float32)
                if self._segment_sampling is not None:
                    self._emit_on_demand_display_and_series(
                        times_array,
                        self._read_display_values(),
                        selected_series_values,
                    )
                else:
                    self._last_time_value = float(times_array[-1])
            else:
                display_steps = [step.display_values for step in steps]
                super()._emit_batch(times_array, display_steps)
        else:
            super()._emit_batch(times_array, steps)
        for binding in self._segment_variable_displays:
            self.emit_update(binding._replace_payload(self))
        if steps and isinstance(steps[0], _SourceStep):
            for index, binding in enumerate(self._segment_variable_histories):
                generation = self._selection_generations.get(
                    binding.selection_id,
                    0,
                )
                sample_indices = np.asarray(
                    [
                        step_index
                        for step_index, step in enumerate(steps)
                        if step.segment_variable_generations[index] == generation
                    ],
                    dtype=np.int64,
                )
                if len(sample_indices) == 0:
                    continue
                samples = [
                    steps[int(step_index)].segment_variable_values[index]
                    for step_index in sample_indices
                ]
                self.emit_update(
                    binding._append_payload(
                        self,
                        times_array[sample_indices],
                        samples,
                    )
                )
            for index, recorder in enumerate(self._recorders):
                sample_indices = _recorder_sample_indices(recorder, times_array)
                if len(sample_indices) == 0:
                    continue
                values = np.stack(
                    [steps[int(step_index)].recorder_values[index] for step_index in sample_indices],
                    axis=1,
                ).astype(np.float32)
                self.emit_update(
                    FieldAppend(
                        field_id=recorder.field_id,
                        append_dim="time",
                        values=values,
                        coord_values=times_array[sample_indices],
                        max_length=recorder.max_samples,
                    )
                )
        self._emit_source_series_updates(auto_sample=False)
        self._emit_source_snapshot_updates()
        self._update_derives(times_array)

    def _observe_derives(self, t: float) -> None:
        for derived in self._derives:
            derived.observe(t)

    def _update_derives(self, times_array: np.ndarray) -> None:
        if not self._derives:
            return
        now = time.monotonic()
        t_last = float(times_array[-1])
        for derived in self._derives:
            if not derived.due(now):
                continue
            result = derived.evaluate(now)
            if result is None:
                continue
            if derived.target == "value":
                value = _state_value(result)
                self.values.set(derived.name, value)
                self.emit_update(ValueChange({derived.name: value}))
                continue
            values = derived.field_values(result)
            if derived.mode == "append":
                self.emit_update(
                    FieldAppend(
                        field_id=derived.field_id,
                        append_dim="time",
                        values=values.reshape(len(derived.series), 1),
                        coord_values=np.asarray([t_last], dtype=np.float32),
                        max_length=derived.max_samples,
                    )
                )
            else:
                self.emit_update(FieldReplace(field_id=derived.field_id, values=values))

    def _recorder_replace(self, recorder: LineRecorder) -> FieldReplace:
        from neuron import h

        t = float(h.t)
        mark_emitted = getattr(recorder, "mark_emitted", None)
        if callable(mark_emitted):
            mark_emitted(t)
        values = recorder.sample_vector().reshape(len(recorder.series), 1)
        return FieldReplace(
            field_id=recorder.field_id,
            values=values,
            coords={
                recorder.series_dim: np.asarray(recorder.series),
                "time": np.asarray([t], dtype=np.float32),
            },
        )

    def _emit_segment_variable_replaces(self) -> None:
        for binding in self._segment_variable_displays:
            self.emit_update(binding._replace_payload(self))
        for binding in self._segment_variable_histories:
            self.emit_update(binding._replace_payload(self))
        for recorder in self._recorders:
            self.emit_update(self._recorder_replace(recorder))

    def on_selection_changed(
        self,
        selection_id: str,
        before: tuple[str, ...],
        after: tuple[str, ...],
        context,
    ) -> None:
        del before, after, context
        self._selection_generations[selection_id] = (
            self._selection_generations.get(selection_id, 0) + 1
        )
        for binding in self._selection_history_bindings.get(selection_id, ()):
            self.emit_update(binding._replace_payload(self))

    def handle_backend_message(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, Reset) and self._segment_sampling is None:
            from neuron import h

            h.finitialize(self.v_init)
            self._last_time_value = float(h.t)
            for derived in self._derives:
                derived.reset()
            self._pending_times = []
            self._pending_steps = []
            self._pending_recorded = []
            self._last_flush_t = None
            self._emit_segment_variable_replaces()
            return
        is_reset = isinstance(payload, Reset)
        super().handle_backend_message(message)
        if is_reset:
            for derived in self._derives:
                derived.reset()
            self._pending_times = []
            self._pending_steps = []
            self._pending_recorded = []
            self._last_flush_t = None
            self._emit_segment_variable_replaces()

    def idle_sleep(self) -> float:
        return 1.0 / 60.0



__all__ = ["SourceBackend"]
