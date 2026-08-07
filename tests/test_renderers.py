"""Renderer registry contract.

Renderers register inside a frontend plugin callback. The registry stays strict
so it catches two different renderers claiming one kind, with an explicit
``override`` escape hatch for intentional replacement.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt6 import QtWidgets

from compneurovis.components.bar.vispy import BarPlotCanvas, BarPlotHost
from compneurovis.components.line.vispy import LinePlotCanvas, LinePlotHost
from compneurovis.core.controls import (
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
)
from compneurovis.core.field import Field
from compneurovis.core.app_spec import (
    AppSpec,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
)
from compneurovis.core.projection import AppProjection
from compneurovis.core.references import AppRef
from compneurovis.core.values import ValueBindingSpec
from compneurovis.core.views import ViewSpec
from compneurovis.frontends.vispy.registries.panel_hosts import (
    _panel_host_factories,
    panel_host_factory,
    register_panel_host,
    registered_panel_kinds,
)
from compneurovis.frontends.vispy.registries.renderers import (
    _factories,
    register_renderer,
)
from compneurovis.frontends.vispy.registries.render_configs import (
    _VIEW_RENDER_CONFIGS,
    register_view_render_config,
)
from compneurovis.frontends.vispy.registries.controls import (
    ActionRenderContext,
    ControlRenderContext,
    ResolvedAction,
    ResolvedControl,
    _action_renderers,
    _control_renderers,
    action_renderer,
    control_renderer,
    register_action_renderer,
    register_control_renderer,
)
from compneurovis.frontends.vispy.panel_manager import PanelManager
from compneurovis.frontends.vispy.controls.panel import ControlsPanel
from compneurovis.frontends.vispy.registries.visual_contributions import (
    PLOT_2D_LAYER_CAPABILITY,
    SCENE_3D_LAYER_CAPABILITY,
    _renderers as _visual_contribution_renderers,
    register_plot_contribution,
    register_scene_contribution,
    visual_contribution_renderer,
)
from compneurovis.frontends.vispy.view3d.viewport import (
    AdjustableTurntableCamera,
)


def test_adjustable_turntable_camera_scales_orbit_pan_and_zoom() -> None:
    camera = AdjustableTurntableCamera(
        distance=20.0,
        azimuth=30.0,
        elevation=30.0,
        orbit_sensitivity=0.5,
        pan_sensitivity=0.25,
        zoom_sensitivity=0.4,
    )

    assert camera.translate_speed == 0.25
    assert camera.zoom_factor == pytest.approx(0.007 * 0.4)

    camera._update_rotation(
        SimpleNamespace(
            mouse_event=SimpleNamespace(
                press_event=SimpleNamespace(pos=np.asarray((0.0, 0.0))),
                pos=np.asarray((10.0, -4.0)),
            )
        )
    )
    assert camera.azimuth == pytest.approx(27.5)
    assert camera.elevation == pytest.approx(29.0)

    camera._scale_factor = 10.0
    wheel = SimpleNamespace(
        handled=False,
        type="mouse_wheel",
        delta=(0.0, 1.0),
    )
    camera.viewbox_mouse_event(wheel)
    factor = 1.1**-0.4
    assert wheel.handled
    assert camera.scale_factor == pytest.approx(10.0 * factor)
    assert camera.distance == pytest.approx(20.0 * factor)


def test_adjustable_turntable_camera_rejects_invalid_sensitivity() -> None:
    with pytest.raises(ValueError, match="camera_pan_sensitivity"):
        AdjustableTurntableCamera(pan_sensitivity=-1.0)


class _RendererA:
    def refresh(self, view, inputs, properties): ...  # pragma: no cover


class _RendererB:
    def refresh(self, view, inputs, properties): ...  # pragma: no cover


def test_first_party_plot_hosts_construct_their_concrete_canvases(
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    line_host = LinePlotHost(
        panel_id="line-panel",
        view_id="line-view",
        title="Line",
    )
    bar_host = BarPlotHost(
        panel_id="bar-panel",
        view_id="bar-view",
        title="Bar",
    )
    try:
        assert isinstance(line_host.plot_2d_panel, LinePlotCanvas)
        assert isinstance(bar_host.plot_2d_panel, BarPlotCanvas)
    finally:
        line_host.close()
        bar_host.close()
        qapp.processEvents()


def test_line_selector_collapses_only_non_output_singleton_dimensions():
    field = Field(
        id="selected_history",
        values=np.zeros((1, 1, 2), dtype=np.float32),
        dims=("variable", "segment", "time"),
        coords={
            "variable": np.asarray(["Voltage"]),
            "segment": np.asarray(["soma@0.5"]),
            "time": np.asarray([0.0, 0.5], dtype=np.float32),
        },
    )

    segment_selector = LinePlotCanvas._filter_selector_for_field(
        field,
        "segment",
        ["soma@0.5"],
        preserve_dimension=False,
    )
    selected = field.select({"segment": segment_selector})
    assert selected.dims == ("variable", "time")
    assert selected.values.shape == (1, 2)

    variable_selector = LinePlotCanvas._filter_selector_for_field(
        field,
        "variable",
        ["Voltage"],
        preserve_dimension=True,
    )
    selected = field.select({"variable": variable_selector})
    assert selected.dims == ("variable", "segment", "time")


def test_line_host_title_follows_a_binding_backed_selector(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = LinePlotHost(
        panel_id="selected-voltage-panel",
        view_id="selected-voltage-view",
        title="Selected segment voltage",
    )
    view = ViewSpec(
        id="selected-voltage-view",
        kind="line_plot",
        title="Selected segment voltage",
        inputs={"data": "selected-history"},
        max_refresh_hz=30.0,
        properties={
            "x_dim": "time",
            "series_dim": "variable",
            "selectors": {
                "segment": ValueBindingSpec("morphology-selection")
            },
        },
    )
    field = Field(
        id="selected-history",
        values=np.zeros((1, 1, 2), dtype=np.float32),
        dims=("variable", "segment", "time"),
        coords={
            "variable": np.asarray(["Voltage"]),
            "segment": np.asarray(["soma@0.5"]),
            "time": np.asarray([0.0, 0.5], dtype=np.float32),
        },
    )
    try:
        host.refresh(
            view,
            {"data": field},
            {},
            {"morphology-selection": ["soma@0.5"]},
        )
        expected = "Selected segment voltage — soma@0.5"
        assert host.plot_2d_panel.resolved_title == expected
        assert host.title() == "Selected segment voltage"

        moved_field = Field(
            id="selected-history",
            values=np.ones((1, 1, 2), dtype=np.float32),
            dims=("variable", "segment", "time"),
            coords={
                "variable": np.asarray(["Voltage"]),
                "segment": np.asarray(["dend@0.75"]),
                "time": np.asarray([0.0, 0.5], dtype=np.float32),
            },
        )
        host.refresh(
            view,
            {"data": moved_field},
            {},
            {"morphology-selection": ["dend@0.75"]},
        )
        expected = "Selected segment voltage — dend@0.75"
        assert host.plot_2d_panel.resolved_title == expected
        assert host.title() == "Selected segment voltage"
    finally:
        host.close()
        qapp.processEvents()


def test_reregistering_the_same_factory_is_idempotent():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_renderer(kind, _RendererA)
        register_renderer(kind, _RendererA)  # same object -> no-op
        assert _factories[kind] is _RendererA
    finally:
        _factories.pop(kind, None)


def test_a_different_renderer_claiming_a_taken_kind_raises():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_renderer(kind, _RendererA)
        with pytest.raises(ValueError, match="already registered"):
            register_renderer(kind, _RendererB)
    finally:
        _factories.pop(kind, None)


def test_override_replaces_intentionally():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_renderer(kind, _RendererA)
        register_renderer(kind, _RendererB, override=True)
        assert _factories[kind] is _RendererB
    finally:
        _factories.pop(kind, None)


def test_view_render_config_registration_is_validated_and_collision_safe():
    kind = "test_render_config"

    def builder_a(view):
        return view

    def builder_b(view):
        return view

    _VIEW_RENDER_CONFIGS.pop(kind, None)
    try:
        register_view_render_config(f"  {kind}  ", builder_a)
        register_view_render_config(kind, builder_a)
        assert _VIEW_RENDER_CONFIGS[kind] is builder_a
        with pytest.raises(ValueError, match="already registered"):
            register_view_render_config(kind, builder_b)
        register_view_render_config(kind, builder_b, override=True)
        assert _VIEW_RENDER_CONFIGS[kind] is builder_b
        with pytest.raises(ValueError, match="cannot be empty"):
            register_view_render_config(" ", builder_a)
        with pytest.raises(TypeError, match="must be callable"):
            register_view_render_config("bad_builder", None)
    finally:
        _VIEW_RENDER_CONFIGS.pop(kind, None)


def test_frontend_exposes_only_panel_addressed_inspection_alias():
    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
    from compneurovis.frontends.vispy.hosts.scene3d import Scene3DPanelLifecycle

    assert "inspection_surface" in VispyFrontendWindow.__dict__
    assert "viewport" not in VispyFrontendWindow.__dict__
    assert "viewport_for" not in VispyFrontendWindow.__dict__
    assert "controls_panel" not in VispyFrontendWindow.__dict__
    assert "viewport" not in Scene3DPanelLifecycle.__dict__


def test_panel_host_registration_is_collision_safe_and_dynamic():
    kind = "test_holographic_panel"

    def factory_a(context, panel):
        return None

    def factory_b(context, panel):
        return None

    _panel_host_factories.pop(kind, None)
    try:
        register_panel_host(kind, factory_a)
        register_panel_host(kind, factory_a)
        assert panel_host_factory(kind) is factory_a
        assert kind in registered_panel_kinds()
        with pytest.raises(ValueError, match="already registered"):
            register_panel_host(kind, factory_b)
        register_panel_host(kind, factory_b, override=True)
        assert panel_host_factory(kind) is factory_b
    finally:
        _panel_host_factories.pop(kind, None)


def test_unknown_panel_kind_requests_deferred_plugin_registration():
    with pytest.raises(LookupError, match="deferred Vispy plugin"):
        panel_host_factory("not_registered")


def test_panel_manager_remounts_only_the_patched_registered_host(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    kind = "test_remountable_panel"
    instances = []

    class Lifecycle:
        compact_when_last = False

        def __init__(self, context, panel):
            del context
            self.panel = panel
            self.host = QtWidgets.QGroupBox(panel.title or "")
            self._pending = False
            self.disposed = False
            instances.append(self)

        @property
        def widget(self):
            return self.host

        @property
        def has_pending_refresh(self):
            return self._pending

        def accepts_refresh_target(self, target):
            return False

        def queue_refresh(self, target):
            del target

        def flush_refreshes(self, **kwargs):
            del kwargs
            return 0

        def update_visibility(self):
            self.host.setVisible(True)

        def dispose(self):
            self.disposed = True

    panel = PanelSpec(id="custom", kind=kind, title="Before")
    app = AppSpec(
        layout_catalog=LayoutCatalog(
            layouts={
                "default": LayoutSpec(
                    panels=(panel,),
                    panel_grid=((panel.id,),),
                )
            },
            active="default",
        )
    )

    class Window:
        def __init__(self):
            self.app_projection = AppProjection(app)

        @property
        def app_spec(self):
            return self.app_projection.spec

        def _active_layout(self):
            return self.app_projection.active_layout()

        def _resolved_panel_grid(self):
            return self._active_layout().panel_grid

        def value_snapshot(self):
            return {}

        def _values_for_fragment(self, fragment_id):
            del fragment_id
            return {}

        def _field(self, *args, **kwargs):
            del args, kwargs
            return None

        def _resolve_view_input(self, *args, **kwargs):
            del args, kwargs
            return None

        def _resolved_controls_and_actions(self, panel_id):
            del panel_id
            return [], []

        def _on_control_changed(self, control, value):
            del control, value

        def _on_action_invoked(self, action, payload):
            del action, payload

        def _on_entity_selected(self, view_id, selection_role, entity_id):
            del view_id, selection_role, entity_id

        def width(self):
            return 800

        def height(self):
            return 600

    _panel_host_factories.pop(kind, None)
    try:
        register_panel_host(kind, Lifecycle)
        stack = QtWidgets.QStackedWidget()
        window = Window()
        manager = PanelManager(window, stack)
        manager.rebuild()
        original = instances[-1]

        assert window.app_projection.patch_panel("custom", title="After")
        assert manager.remount("custom")
        qapp.processEvents()

        assert original.disposed
        assert len(instances) == 2
        assert instances[-1].widget.title() == "After"
        assert manager.panel_hosts["custom"] is instances[-1]
    finally:
        _panel_host_factories.pop(kind, None)


def test_panel_manager_refreshes_continuously_dirty_hosts_fairly(monkeypatch):
    clock = [0.0]
    service_order = []

    class Lifecycle:
        has_pending_refresh = True

        def __init__(self, panel_id):
            self.panel_id = panel_id

        def flush_refreshes(self, **_kwargs):
            service_order.append(self.panel_id)
            clock[0] = 2.0
            return 1

    monkeypatch.setattr(
        "compneurovis.frontends.vispy.panel_manager.time.monotonic",
        lambda: clock[0],
    )
    manager = PanelManager(None, None)
    manager.panel_hosts = {
        panel_id: Lifecycle(panel_id)
        for panel_id in ("expensive", "line-a", "line-b")
    }

    for _ in range(3):
        clock[0] = 0.0
        assert manager.flush(now=0.0, refresh_deadline_s=1.0) == 1

    assert service_order == ["expensive", "line-a", "line-b"]


def test_control_and_action_renderer_registries_are_open_and_collision_safe():
    control_kind = "test_knob"
    action_kind = "test_split_button"

    def control_a(panel, spec, value):
        return ("a", value)

    def control_b(panel, spec, value):
        return ("b", value)

    def action_a(panel, spec, values):
        return ("action", values)

    _control_renderers.pop(control_kind, None)
    _action_renderers.pop(action_kind, None)
    try:
        register_control_renderer(control_kind, control_a, full_width=True)
        register_control_renderer(control_kind, control_a, full_width=True)
        registration = control_renderer(control_kind)
        assert registration.factory is control_a
        assert registration.full_width
        with pytest.raises(ValueError, match="already registered"):
            register_control_renderer(control_kind, control_b)
        register_control_renderer(control_kind, control_b, override=True)
        assert control_renderer(control_kind).factory is control_b

        register_action_renderer(action_kind, action_a)
        assert action_renderer(action_kind).factory is action_a
        with pytest.raises(ValueError, match="already registered"):
            register_action_renderer(action_kind, control_a)
    finally:
        _control_renderers.pop(control_kind, None)
        _action_renderers.pop(action_kind, None)


def test_third_party_control_renderer_emits_through_public_context(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    kind = "test_emitting_knob"
    observed = []

    def render(
        context: ControlRenderContext,
        control: ControlSpec,
        current,
    ):
        assert current == 0.25
        button = QtWidgets.QPushButton(control.label)
        button.clicked.connect(lambda: context.emit(0.75))
        return button

    control = ControlSpec(
        id="gain",
        label="Gain",
        value_spec=ControlValueSpec(kind="scalar", default=0.25),
        presentation=ControlPresentationSpec(kind=kind),
    )
    _control_renderers.pop(kind, None)
    try:
        register_control_renderer(kind, render)
        resolved = ResolvedControl(
            ref=AppRef("gain"),
            value_ref=AppRef("gain"),
            spec=control,
        )
        panel = ControlsPanel(
            lambda item, value: observed.append((item.ref, value))
        )
        panel.set_controls([resolved], [], {})
        panel.widgets[resolved.ref].click()
        qapp.processEvents()

        assert observed == [(AppRef("gain"), 0.75)]
    finally:
        _control_renderers.pop(kind, None)


def test_third_party_action_renderer_invokes_through_public_context(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    kind = "test_action_context"
    observed = []

    def render(context: ActionRenderContext, action, values):
        assert values == {"gain": 0.5}
        button = QtWidgets.QPushButton(action.label)
        button.clicked.connect(context.invoke)
        return button

    from compneurovis.core.controls import ActionSpec

    action = ActionSpec(
        id="apply",
        label="Apply",
        payload={"gain": ValueBindingSpec("gain")},
        presentation_kind=kind,
    )
    _action_renderers.pop(kind, None)
    try:
        register_action_renderer(kind, render)
        resolved = ResolvedAction(ref=AppRef("apply"), spec=action)
        panel = ControlsPanel(
            lambda spec, value: None,
            lambda item, payload: observed.append((item.ref, payload)),
        )
        panel.set_controls([], [resolved], {"gain": 0.5})
        panel.widgets[resolved.ref].click()
        qapp.processEvents()

        assert observed == [(AppRef("apply"), {"gain": 0.5})]
    finally:
        _action_renderers.pop(kind, None)


def test_visual_contribution_kinds_are_scoped_by_target_capability():
    kind = "test_halo"

    def scene_factory(*args):
        return ("scene", args)

    def plot_factory(*args):
        return ("plot", args)

    scene_key = (SCENE_3D_LAYER_CAPABILITY, kind)
    plot_key = (PLOT_2D_LAYER_CAPABILITY, kind)
    _visual_contribution_renderers.pop(scene_key, None)
    _visual_contribution_renderers.pop(plot_key, None)
    try:
        register_scene_contribution(kind, scene_factory)
        register_plot_contribution(kind, plot_factory)
        assert (
            visual_contribution_renderer(*scene_key).factory is scene_factory
        )
        assert visual_contribution_renderer(*plot_key).factory is plot_factory
        with pytest.raises(ValueError, match="already registered"):
            register_scene_contribution(kind, plot_factory)
        with pytest.raises(LookupError, match="no visual contribution renderer"):
            visual_contribution_renderer(
                SCENE_3D_LAYER_CAPABILITY, "not_registered"
            )
    finally:
        _visual_contribution_renderers.pop(scene_key, None)
        _visual_contribution_renderers.pop(plot_key, None)
