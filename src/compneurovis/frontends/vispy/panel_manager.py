"""Panel construction, layout, lifecycle, and refresh coordination."""

from __future__ import annotations

import time
from types import MappingProxyType
from typing import Any

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core import AppRef
from compneurovis.core.runtime.performance import perf_log
from compneurovis.frontends.vispy.registries.panel_hosts import (
    PanelHostContext,
    PanelHostLifecycle,
    panel_host_factory,
)
from compneurovis.frontends.vispy.refresh_planning import (
    RefreshTarget,
    _target_kind_counts,
)


class PanelManager:
    """Own all live panel hosts and their Qt layout."""

    def __init__(self, window: Any, stack: QtWidgets.QStackedWidget) -> None:
        self.window = window
        self.stack = stack
        self.view_to_panel_id: dict[str | AppRef, str] = {}
        self.inspection_surfaces: dict[str, dict[str, Any]] = {}
        self.panel_hosts: dict[str, PanelHostLifecycle] = {}
        self._last_refresh_s_by_panel: dict[str, float] = {}
        self._refresh_revision_by_panel: dict[str, int] = {}
        self.layout_splitter: QtWidgets.QSplitter | None = None

    def rebuild(self) -> None:
        started = time.monotonic()
        for lifecycle in self.panel_hosts.values():
            lifecycle.dispose()
        self.panel_hosts.clear()
        self._last_refresh_s_by_panel.clear()
        self._refresh_revision_by_panel.clear()
        self.view_to_panel_id.clear()
        self.inspection_surfaces.clear()

        if self.layout_splitter is not None:
            index = self.stack.indexOf(self.layout_splitter)
            if index >= 0:
                self.stack.removeWidget(self.layout_splitter)
            self.layout_splitter.deleteLater()

        outer = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        outer.setChildrenCollapsible(False)
        outer.setOpaqueResize(False)
        self.layout_splitter = outer

        for row_cells in self.window._resolved_panel_grid():
            if len(row_cells) == 1:
                widget = self.make_panel(row_cells[0])
                if widget is not None:
                    outer.addWidget(widget)
                continue
            row = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
            row.setChildrenCollapsible(False)
            row.setOpaqueResize(False)
            for cell in row_cells:
                widget = self.make_panel(cell)
                if widget is not None:
                    row.addWidget(widget)
            outer.addWidget(row)

        self.stack.addWidget(outer)
        perf_log(
            "frontend",
            "rebuild_panels",
            row_count=outer.count(),
            panel_host_count=len(self.panel_hosts),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def make_panel(self, cell_id: str) -> QtWidgets.QWidget | None:
        started = time.monotonic()
        window = self.window
        if window.app_spec is None:
            return None
        panel_spec = window._active_layout().panel(cell_id)
        if panel_spec is None:
            return None
        lifecycle = self._create_lifecycle(panel_spec)
        self._register_lifecycle(panel_spec, lifecycle)
        perf_log(
            "frontend",
            "create_panel",
            panel_id=panel_spec.id,
            panel_kind=panel_spec.kind,
            view_ids=panel_spec.view_ids,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )
        return lifecycle.widget

    def _create_lifecycle(self, panel_spec):
        window = self.window
        context = PanelHostContext(
            app_spec_provider=lambda: window.app_spec,
            active_layout=window._active_layout,
            value_snapshot=window.value_snapshot,
            values_for_fragment=window._values_for_fragment,
            field=window._field,
            fields=lambda: MappingProxyType(window.app_projection.fields),
            resolve_input=window._resolve_view_input,
            controls_and_actions=window._resolved_controls_and_actions,
            control_changed=window._on_control_changed,
            action_invoked=window._on_action_invoked,
            entity_selected=window._on_entity_selected,
        )
        lifecycle = panel_host_factory(panel_spec.kind)(context, panel_spec)
        if not isinstance(lifecycle, PanelHostLifecycle):
            raise TypeError(
                f"Panel-host factory for {panel_spec.kind!r} must return a "
                "PanelHostLifecycle"
            )
        if not isinstance(lifecycle.widget, QtWidgets.QWidget):
            raise TypeError(
                f"Panel-host factory for {panel_spec.kind!r} must expose a QWidget"
            )
        return lifecycle

    def _register_lifecycle(self, panel_spec, lifecycle) -> None:
        self.panel_hosts[panel_spec.id] = lifecycle
        self._refresh_revision_by_panel.setdefault(panel_spec.id, 0)
        for view_id in panel_spec.view_ids:
            self.view_to_panel_id[view_id] = panel_spec.id
        inspection = getattr(lifecycle, "inspection_surfaces", {})
        if callable(inspection):
            inspection = inspection()
        inspection = {} if inspection is None else dict(inspection)
        if inspection:
            self.inspection_surfaces[panel_spec.id] = inspection

    def _unregister_lifecycle(self, panel_id: str) -> None:
        self.panel_hosts.pop(panel_id, None)
        self._last_refresh_s_by_panel.pop(panel_id, None)
        self._refresh_revision_by_panel.pop(panel_id, None)
        self.inspection_surfaces.pop(panel_id, None)
        for view_id, owner_panel_id in tuple(self.view_to_panel_id.items()):
            if owner_panel_id == panel_id:
                self.view_to_panel_id.pop(view_id, None)

    def inspection_surface(self, panel_id: str, name: str) -> Any | None:
        return self.inspection_surfaces.get(panel_id, {}).get(name)

    def remount(self, panel_id: str) -> bool:
        """Reconstruct exactly one mounted panel from the live projection."""
        previous = self.panel_hosts.get(panel_id)
        panel_spec = self.window._active_layout().panel(panel_id)
        if previous is None or panel_spec is None:
            return False
        previous_widget = previous.widget
        parent = previous_widget.parentWidget()
        if not isinstance(parent, QtWidgets.QSplitter):
            raise RuntimeError(
                f"Mounted panel {panel_id!r} is not owned by a layout splitter"
            )
        index = parent.indexOf(previous_widget)
        if index < 0:
            raise RuntimeError(
                f"Mounted panel {panel_id!r} is missing from its layout splitter"
            )

        replacement = self._create_lifecycle(panel_spec)
        replaced_widget = parent.replaceWidget(index, replacement.widget)
        if replaced_widget is None:
            replacement.dispose()
            raise RuntimeError(f"Could not remount panel {panel_id!r}")

        previous.dispose()
        self._unregister_lifecycle(panel_id)
        self._register_lifecycle(panel_spec, replacement)
        replaced_widget.setParent(None)
        replaced_widget.deleteLater()
        self.apply_sizes()
        return True

    def update_visibility(self) -> None:
        for lifecycle in self.panel_hosts.values():
            lifecycle.update_visibility()
        self.apply_sizes()

    def apply_sizes(self) -> None:
        if self.layout_splitter is None:
            return
        width = max(self.window.width(), 1)
        height = max(self.window.height(), 1)
        row_count = self.layout_splitter.count()
        if row_count == 0:
            return
        last_widget = self.layout_splitter.widget(row_count - 1)
        last_is_compact = any(
            lifecycle.widget is last_widget and lifecycle.compact_when_last
            for lifecycle in self.panel_hosts.values()
        )
        if last_is_compact and row_count > 1:
            compact_height = min(
                max(140, int(height * 0.28)), max(140, int(height * 0.45))
            )
            row_height = max(1, int((height - compact_height) / (row_count - 1)))
            sizes = [row_height] * (row_count - 1) + [compact_height]
        else:
            sizes = [max(1, int(height / row_count))] * row_count
        self.layout_splitter.setSizes(sizes)
        for index in range(row_count):
            row_widget = self.layout_splitter.widget(index)
            if isinstance(row_widget, QtWidgets.QSplitter) and row_widget.count():
                row_widget.setSizes(
                    [max(1, int(width / row_widget.count()))] * row_widget.count()
                )

    def apply_refresh_targets(
        self,
        targets: set[RefreshTarget],
        *,
        force: bool = False,
        refresh_deadline_s: float | None = None,
    ) -> None:
        if not targets:
            return
        started = time.monotonic()
        claimed = 0
        for target in sorted(
            targets, key=lambda item: (str(item.view_id or ""), item.kind)
        ):
            for lifecycle in self.panel_hosts.values():
                if lifecycle.accepts_refresh_target(target):
                    lifecycle.queue_refresh(target)
                    claimed += 1
        refreshed = 0
        if refresh_deadline_s is None or time.monotonic() < refresh_deadline_s:
            refreshed = self.flush(
                force=force,
                now=started,
                refresh_deadline_s=refresh_deadline_s,
            )
        perf_log(
            "frontend",
            "apply_refresh_targets",
            target_count=len(targets),
            target_kinds=_target_kind_counts(targets),
            claimed_target_count=claimed,
            refreshed_panel_count=refreshed,
            deferred_panel_count=sum(
                int(lifecycle.has_pending_refresh)
                for lifecycle in self.panel_hosts.values()
            ),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def flush(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> int:
        refreshed = 0
        pending = [
            (panel_id, lifecycle)
            for panel_id, lifecycle in self.panel_hosts.items()
            if lifecycle.has_pending_refresh
        ]
        pending.sort(
            key=lambda item: self._last_refresh_s_by_panel.get(
                item[0], float("-inf")
            )
        )
        for panel_id, lifecycle in pending:
            if refresh_deadline_s is not None and time.monotonic() >= refresh_deadline_s:
                break
            refresh_count = lifecycle.flush_refreshes(
                force=force,
                now=now,
                refresh_deadline_s=refresh_deadline_s,
            )
            if refresh_count:
                self._last_refresh_s_by_panel[panel_id] = time.monotonic()
                self._refresh_revision_by_panel[panel_id] = (
                    self._refresh_revision_by_panel.get(panel_id, 0)
                    + refresh_count
                )
                refreshed += refresh_count
        return refreshed

    def panel_refresh_revisions(self) -> MappingProxyType:
        """Snapshot panel presentation revisions for frontend projections."""
        return MappingProxyType(dict(self._refresh_revision_by_panel))

    def has_pending_refreshes(self) -> bool:
        return any(
            lifecycle.has_pending_refresh for lifecycle in self.panel_hosts.values()
        )

    def flush_due(
        self, *, now: float, refresh_deadline_s: float | None = None
    ) -> None:
        if self.has_pending_refreshes() and (
            refresh_deadline_s is None or time.monotonic() < refresh_deadline_s
        ):
            self.flush(now=now, refresh_deadline_s=refresh_deadline_s)


__all__ = ["PanelManager"]
