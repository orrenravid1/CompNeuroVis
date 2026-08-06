"""Frontend update compaction and projection mutation."""

from __future__ import annotations

import sys
import time
from typing import Any

import numpy as np

from compneurovis.core import AppRef, app_ref, ControlSpec, DEFAULT_FRAGMENT_ID
from compneurovis.core.messages import (
    AppMetadataPatch,
    AppSpecDeclared,
    ControlPatch,
    FieldAppend,
    FieldReplace,
    LayoutReplace,
    Message,
    MessagePayload,
    OperatorPatch,
    PanelPatch,
    RoutedMessage,
    Status,
    ValueChange,
    ViewPatch,
)
from compneurovis.core.runtime.performance import perf_log
from compneurovis.frontends.vispy.refresh_planning import (
    RefreshTarget,
    _target_kind_counts,
)

HANDLE_MESSAGES_LOG_THRESHOLD_MS = 5.0


def _coords_are_equal(
    left: dict[str, np.ndarray], right: dict[str, np.ndarray]
) -> bool:
    if left.keys() != right.keys():
        return False
    return all(
        np.array_equal(np.asarray(left[key]), np.asarray(right[key])) for key in left
    )


def _update_type_counts(updates: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for update in updates:
        name = type(update).__name__
        counts[name] = counts.get(name, 0) + 1
    return counts


def _replace_message_payload(
    message: Message[MessagePayload], payload: MessagePayload
) -> Message[MessagePayload]:
    return Message(
        type=message.type,
        intent=message.intent,
        payload=payload,
        tags=message.tags,
    )


def _message_fragment_id(message: Message[MessagePayload]) -> str:
    return str(message.tags.get("fragment_id", DEFAULT_FRAGMENT_ID))


def _scoped_value_key(control: ControlSpec, fragment_id: str) -> AppRef:
    return app_ref(control.value_key or control.id, fragment_id=fragment_id)


class AppUpdateProcessor:
    """Apply canonical update messages to one frontend window projection."""

    def __init__(self, window: Any) -> None:
        self.window = window

    def __getattr__(self, name: str) -> Any:
        return getattr(self.window, name)

    def compact_update_messages(
        self, messages: list[Message[MessagePayload]]
    ) -> list[Message[MessagePayload]]:
        """Coalesce stale visual updates before applying a frontend backlog."""

        if not messages or self.app_projection is None:
            return messages
        if any(isinstance(message.payload, AppSpecDeclared) for message in messages):
            return messages

        compacted: list[Message[MessagePayload]] = []
        pending: dict[AppRef, dict[str, Message[MessagePayload] | None]] = {}
        pending_order: list[AppRef] = []
        dropped_field_replace_count = 0
        merged_field_append_count = 0

        def field_ref_for(message: Message[MessagePayload], field_id: str) -> AppRef:
            return app_ref(field_id, fragment_id=_message_fragment_id(message))

        def ensure_field(
            field_ref: AppRef,
        ) -> dict[str, Message[MessagePayload] | None]:
            if field_ref not in pending:
                pending[field_ref] = {"replace": None, "append": None}
                pending_order.append(field_ref)
            return pending[field_ref]

        def flush_field(field_ref: AppRef) -> None:
            slot = pending.pop(field_ref, None)
            if slot is None:
                return
            replace_message = slot.get("replace")
            append_message = slot.get("append")
            if replace_message is not None:
                compacted.append(replace_message)
            if append_message is not None:
                compacted.append(append_message)
            try:
                pending_order.remove(field_ref)
            except ValueError:
                pass

        def flush_pending() -> None:
            for field_ref in tuple(pending_order):
                flush_field(field_ref)

        for message in messages:
            update = message.payload
            if isinstance(update, FieldReplace):
                field_ref = field_ref_for(message, update.field_id)
                slot = ensure_field(field_ref)
                previous = slot.get("replace")
                if previous is not None and isinstance(previous.payload, FieldReplace):
                    dropped_field_replace_count += 1
                    attrs_update = {
                        **previous.payload.attrs_update,
                        **update.attrs_update,
                    }
                    coords = (
                        update.coords
                        if update.coords is not None
                        else previous.payload.coords
                    )
                    update = FieldReplace(
                        field_id=update.field_id,
                        values=update.values,
                        coords=coords,
                        attrs_update=attrs_update,
                    )
                    message = _replace_message_payload(message, update)
                slot["replace"] = message
                slot["append"] = None
                continue
            if isinstance(update, FieldAppend):
                field_ref = field_ref_for(message, update.field_id)
                slot = ensure_field(field_ref)
                previous = slot.get("append")
                if previous is None:
                    slot["append"] = self._trim_field_append_message(message)
                    continue
                merged = self._merge_field_append_messages(previous, message)
                if merged is None:
                    flush_field(field_ref)
                    ensure_field(field_ref)["append"] = self._trim_field_append_message(
                        message
                    )
                else:
                    merged_field_append_count += 1
                    slot["append"] = merged
                continue

            flush_pending()
            compacted.append(message)

        flush_pending()
        if len(compacted) != len(messages):
            perf_log(
                "frontend",
                "compact_update_messages",
                before_count=len(messages),
                after_count=len(compacted),
                dropped_field_replace_count=dropped_field_replace_count,
                merged_field_append_count=merged_field_append_count,
                update_types_before=_update_type_counts(
                    [message.payload for message in messages]
                ),
                update_types_after=_update_type_counts(
                    [message.payload for message in compacted]
                ),
            )
        return compacted

    def _merge_field_append_messages(
        self,
        left_message: Message[MessagePayload],
        right_message: Message[MessagePayload],
    ) -> Message[MessagePayload] | None:
        left = left_message.payload
        right = right_message.payload
        if not isinstance(left, FieldAppend) or not isinstance(right, FieldAppend):
            return None
        if _message_fragment_id(left_message) != _message_fragment_id(right_message):
            return None
        if (
            left.field_id != right.field_id
            or left.append_dim != right.append_dim
            or left.max_length != right.max_length
        ):
            return None
        field_ref = app_ref(
            left.field_id, fragment_id=_message_fragment_id(left_message)
        )
        field = (
            self.app_projection.field(field_ref)
            if self.app_projection is not None
            else None
        )
        if field is None:
            return None
        try:
            axis = field.axis_index(left.append_dim)
            merged = FieldAppend(
                field_id=left.field_id,
                append_dim=left.append_dim,
                values=np.concatenate([left.values, right.values], axis=axis),
                coord_values=np.concatenate(
                    [left.coord_values, right.coord_values], axis=0
                ),
                max_length=right.max_length,
                attrs_update={**left.attrs_update, **right.attrs_update},
            )
        except Exception:
            return None
        return self._trim_field_append_message(
            _replace_message_payload(right_message, merged)
        )

    def _trim_field_append_message(
        self,
        message: Message[MessagePayload],
    ) -> Message[MessagePayload]:
        update = message.payload
        if not isinstance(update, FieldAppend):
            return message
        trimmed = self._trim_field_append(
            update, fragment_id=_message_fragment_id(message)
        )
        if trimmed is update:
            return message
        return _replace_message_payload(message, trimmed)

    def _trim_field_append(
        self, update: FieldAppend, *, fragment_id: str
    ) -> FieldAppend:
        if update.max_length is None or update.max_length < 0:
            return update
        max_length = int(update.max_length)
        if len(update.coord_values) <= max_length:
            return update
        field = self._field(update.field_id, fragment_id=fragment_id)
        if field is None:
            return update
        axis = field.axis_index(update.append_dim)
        slicers = [slice(None)] * np.asarray(update.values).ndim
        slicers[axis] = slice(0, 0) if max_length == 0 else slice(-max_length, None)
        return FieldAppend(
            field_id=update.field_id,
            append_dim=update.append_dim,
            values=np.asarray(update.values)[tuple(slicers)],
            coord_values=np.asarray(update.coord_values)[:0]
            if max_length == 0
            else np.asarray(update.coord_values)[-max_length:],
            max_length=update.max_length,
            attrs_update=update.attrs_update,
        )

    def handle_update_messages(
        self,
        messages: list[Message[MessagePayload]],
        *,
        poll_started: float,
        timer_gap_ms: float | None,
        refresh_deadline_s: float | None = None,
    ) -> None:
        handle_started = time.monotonic()
        pending_targets: set[RefreshTarget] = set()
        pending_status: str | None = None
        pending_field_appends: dict[AppRef, FieldAppend] = {}
        flushed_field_appends = 0
        appended_samples_by_field: dict[str, int] = {}
        field_append_apply_ms = 0.0
        field_replace_apply_ms = 0.0
        field_replace_count = 0
        refresh_apply_ms = 0.0
        updates = [message.payload for message in messages]

        for message in messages:
            update = message.payload
            if isinstance(update, AppSpecDeclared) and self.app_projection is None:
                self._set_app_spec(update.app_spec)

        def flush_pending_field_appends() -> None:
            nonlocal pending_targets, flushed_field_appends, field_append_apply_ms
            if not pending_field_appends:
                return
            if self.app_spec is None:
                pending_field_appends.clear()
                return
            for field_ref, update in pending_field_appends.items():
                append_started = time.monotonic()
                flushed_field_appends += 1
                field_key = str(field_ref)
                appended_samples_by_field[field_key] = appended_samples_by_field.get(
                    field_key, 0
                ) + int(len(update.coord_values))
                current = self.app_projection.fields[field_ref]
                axis = current.axis_index(update.append_dim)
                existing_length = int(current.values.shape[axis])
                self.app_projection.fields[field_ref] = current.append(
                    update.append_dim,
                    update.values,
                    update.coord_values,
                    max_length=update.max_length,
                    attrs_update=update.attrs_update,
                )
                append_duration_ms = round(
                    (time.monotonic() - append_started) * 1000.0, 3
                )
                field_append_apply_ms += append_duration_ms
                if append_duration_ms >= 5.0:
                    perf_log(
                        "frontend",
                        "field_append_apply_hiccup",
                        field_id=str(field_ref),
                        append_dim=update.append_dim,
                        existing_length=existing_length,
                        append_sample_count=int(len(update.coord_values)),
                        max_length=update.max_length,
                        values_shape=getattr(update.values, "shape", None),
                        duration_ms=append_duration_ms,
                    )
                if self.refresh_planner is not None:
                    pending_targets.update(
                        self.refresh_planner.targets_for_field_replace(field_ref)
                    )
            pending_field_appends.clear()

        update_loop_started = time.monotonic()
        for message in messages:
            update = message.payload
            fragment_id = _message_fragment_id(message)
            if isinstance(update, FieldAppend):
                if self.app_spec is None:
                    continue
                field_ref = app_ref(update.field_id, fragment_id=fragment_id)
                update = self._trim_field_append(update, fragment_id=fragment_id)
                pending = pending_field_appends.get(field_ref)
                if pending is None:
                    pending_field_appends[field_ref] = update
                    continue
                if (
                    pending.append_dim != update.append_dim
                    or pending.max_length != update.max_length
                ):
                    flush_pending_field_appends()
                    pending_field_appends[field_ref] = update
                    continue
                axis = self.app_projection.fields[field_ref].axis_index(
                    update.append_dim
                )
                pending_field_appends[field_ref] = self._trim_field_append(
                    FieldAppend(
                        field_id=update.field_id,
                        append_dim=update.append_dim,
                        values=np.concatenate(
                            [pending.values, update.values], axis=axis
                        ),
                        coord_values=np.concatenate(
                            [pending.coord_values, update.coord_values], axis=0
                        ),
                        max_length=update.max_length,
                        attrs_update={**pending.attrs_update, **update.attrs_update},
                    ),
                    fragment_id=fragment_id,
                )
                continue

            flush_pending_field_appends()
            if isinstance(update, FieldReplace):
                if self.app_spec is None:
                    continue
                field_ref = app_ref(update.field_id, fragment_id=fragment_id)
                replace_started = time.monotonic()
                field_replace_count += 1
                current = self.app_projection.fields[field_ref]
                coords_changed = update.coords is not None and not _coords_are_equal(
                    current.coords, update.coords
                )
                coords = (
                    current.coords
                    if update.coords is None or not coords_changed
                    else update.coords
                )
                self.app_projection.fields[field_ref] = current.with_values(
                    update.values, coords=coords, attrs_update=update.attrs_update
                )
                replace_duration_ms = round(
                    (time.monotonic() - replace_started) * 1000.0, 3
                )
                field_replace_apply_ms += replace_duration_ms
                if replace_duration_ms >= 5.0:
                    perf_log(
                        "frontend",
                        "field_replace_apply_hiccup",
                        field_id=str(field_ref),
                        coords_changed=coords_changed,
                        values_shape=getattr(update.values, "shape", None),
                        duration_ms=replace_duration_ms,
                    )
                if self.refresh_planner is not None:
                    pending_targets.update(
                        self.refresh_planner.targets_for_field_replace(
                            field_ref, coords_changed=coords_changed
                        )
                    )
            elif isinstance(update, ViewPatch):
                if self.app_projection is None:
                    continue
                view_ref = app_ref(update.view_id, fragment_id=fragment_id)
                self.app_projection.replace_view(view_ref, update.updates)
                if self.refresh_planner is not None:
                    pending_targets.update(
                        self.refresh_planner.targets_for_view_patch(
                            view_ref, set(update.updates.keys())
                        )
                    )
            elif isinstance(update, OperatorPatch):
                if self.app_projection is None:
                    continue
                operator_ref = app_ref(update.operator_id, fragment_id=fragment_id)
                self.app_projection.replace_operator(operator_ref, update.updates)
                if self.refresh_planner is not None:
                    pending_targets.update(
                        self.refresh_planner.targets_for_operator_patch(
                            operator_ref, set(update.updates.keys())
                        )
                    )
            elif isinstance(update, ControlPatch):
                if self.app_projection is None:
                    continue
                control_ref = app_ref(update.control_id, fragment_id=fragment_id)
                self.app_projection.replace_control(control_ref, update.updates)
                pending_targets.add(RefreshTarget.CONTROLS)
            elif isinstance(update, AppMetadataPatch):
                if self.app_spec is None:
                    continue
                self.app_projection.metadata.update(update.updates)
            elif isinstance(update, PanelPatch):
                if self.app_projection is None:
                    continue
                changes: dict[str, Any] = {}
                if update.control_ids is not None:
                    changes["control_ids"] = tuple(
                        app_ref(item, fragment_id=fragment_id)
                        for item in update.control_ids
                    )
                if update.action_ids is not None:
                    changes["action_ids"] = tuple(
                        app_ref(item, fragment_id=fragment_id)
                        for item in update.action_ids
                    )
                if update.view_ids is not None:
                    changes["view_ids"] = tuple(
                        app_ref(item, fragment_id=fragment_id)
                        for item in update.view_ids
                    )
                if update.title is not None:
                    changes["title"] = update.title
                panel_id = (
                    update.panel_id
                    if fragment_id == DEFAULT_FRAGMENT_ID
                    else f"{fragment_id}:{update.panel_id}"
                )
                if changes and self.app_projection.patch_panel(panel_id, **changes):
                    pending_targets.add(RefreshTarget.CONTROLS)
            elif isinstance(update, LayoutReplace):
                if self.app_projection is None:
                    continue
                self.app_projection.replace_active_layout_panels(
                    update.panels, update.panel_grid
                )
                self._rebuild_panels()
                self._update_panel_visibility()
                if self.refresh_planner is not None:
                    pending_targets.update(self.refresh_planner.full_refresh_targets())
            elif isinstance(update, ValueChange):
                if self.refresh_planner is None:
                    continue
                control_value_keys = set()
                if self.app_spec is not None:
                    control_value_keys = {
                        _scoped_value_key(control, control_ref.fragment_id)
                        for control_ref, control in self.app_spec.iter_controls()
                    }
                for key, value in update.updates.items():
                    scoped_key = app_ref(key, fragment_id=fragment_id)
                    self._apply_frontend_value(scoped_key, value)
                    pending_targets.update(
                        self.refresh_planner.targets_for_value_change(scoped_key)
                    )
                    if scoped_key in control_value_keys:
                        pending_targets.add(RefreshTarget.CONTROLS)
            elif isinstance(update, Status):
                if update.message:
                    if update.timeout_ms is not None:
                        self.statusBar().showMessage(update.message, update.timeout_ms)
                    else:
                        pending_status = update.message
                else:
                    self.statusBar().clearMessage()
            elif isinstance(update, (AppSpecDeclared, RoutedMessage)):
                continue
            else:
                msg = getattr(update, "message", str(update))
                pending_status = msg
                sys.stderr.write(f"{msg.rstrip()}\n")
                sys.stderr.flush()
        flush_pending_field_appends()
        update_loop_ms = round((time.monotonic() - update_loop_started) * 1000.0, 3)
        if pending_targets:
            refresh_started = time.monotonic()
            self._apply_refresh_targets(
                pending_targets, refresh_deadline_s=refresh_deadline_s
            )
            refresh_apply_ms += round((time.monotonic() - refresh_started) * 1000.0, 3)
        if (
            self._has_pending_panel_refreshes()
            and (refresh_deadline_s is None or time.monotonic() < refresh_deadline_s)
        ):
            refresh_started = time.monotonic()
            self._flush_panel_host_refreshes(
                refresh_deadline_s=refresh_deadline_s
            )
            refresh_apply_ms += round((time.monotonic() - refresh_started) * 1000.0, 3)
        if pending_status is not None:
            self.statusBar().showMessage(pending_status)
        local_duration_ms = round((time.monotonic() - handle_started) * 1000.0, 3)
        duration_ms = round((time.monotonic() - poll_started) * 1000.0, 3)
        should_log_handle = (
            local_duration_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or update_loop_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or refresh_apply_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or field_append_apply_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or field_replace_apply_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or len(updates) > 8
            or pending_status is not None
            or any(isinstance(update, AppSpecDeclared) for update in updates)
        )
        if should_log_handle:
            perf_log(
                "frontend",
                "handle_messages",
                update_count=len(updates),
                update_types=_update_type_counts(updates),
                coalesced_field_append_count=flushed_field_appends,
                appended_samples_by_field=appended_samples_by_field,
                field_append_apply_ms=round(field_append_apply_ms, 3),
                field_replace_count=field_replace_count,
                field_replace_apply_ms=round(field_replace_apply_ms, 3),
                update_loop_ms=update_loop_ms,
                refresh_apply_ms=round(refresh_apply_ms, 3),
                pending_target_count=len(pending_targets),
                pending_target_kinds=_target_kind_counts(pending_targets),
                dirty_panel_count=sum(
                    int(lifecycle.has_pending_refresh)
                    for lifecycle in self._panel_hosts.values()
                ),
                timer_gap_ms=timer_gap_ms,
                local_duration_ms=local_duration_ms,
                duration_ms=duration_ms,
            )



__all__ = ["AppUpdateProcessor"]
