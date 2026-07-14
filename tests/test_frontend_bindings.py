import io
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
import pytest

from compneurovis import (
    ActionSpec,
    AppSpec,
    BoolValueSpec,
    ChoiceValueSpec,
    ControlPresentationSpec,
    ControlSpec,
    DiagnosticsSpec,
    Field,
    GridSliceOperatorSpec,
    LayoutSpec,
    LinePlotViewSpec,
    MorphologyGeometry,
    MorphologyViewSpec,
    PanelSpec,
    ScalarValueSpec,
    RunSpec,
    StateBinding,
    StateGraphViewSpec,
    SurfaceViewSpec,
    VispyFrontendWindow,
    XYValueSpec,
    build_neuron_app,
    build_surface_app,
    grid_field,
)
from compneurovis.backends.neuron import NeuronBackend
from compneurovis.backends.neuron.app_spec import NeuronAppSpecBuilder
from compneurovis.frontends.vispy import frontend as frontend_module
from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner, RefreshTarget
from compneurovis.frontends.vispy.panels.controls import (
    ControlsHostPanel,
    ControlsPanel,
)
from compneurovis.frontends.vispy.panels.line_plot import (
    LinePlotHostPanel,
    LinePlotPanel,
)
from compneurovis.frontends.vispy.panels.state_graph import (
    StateGraphPanel,
    _state_label_color_for_fill,
    _state_node_colormap_name,
)
from compneurovis.frontends.vispy.renderers.morphology import MorphologyRenderer
from compneurovis.frontends.vispy.view3d.viewport import Viewport3DPanel
from compneurovis.frontends.vispy.view3d.visuals import (
    MORPHOLOGY_3D_VISUAL_KEY,
    SURFACE_3D_VISUAL_KEY,
    Surface3DVisual,
)
from compneurovis.backends import (
    BackendBase,
    resolve_interaction_target_source,
)
from compneurovis.messages import (
    Error,
    FieldAppend,
    FieldReplace,
    Reset,
    SetControl,
    StatePatch,
    update_message,
)


def view_3d_panel(panel_id: str, view_id: str, **kwargs) -> PanelSpec:
    return PanelSpec(id=panel_id, kind="view_3d", view_ids=(view_id,), **kwargs)


def line_plot_panel_spec(panel_id: str, view_id: str, **kwargs) -> PanelSpec:
    return PanelSpec(id=panel_id, kind="line_plot", view_ids=(view_id,), **kwargs)


def controls_panel_spec(panel_id: str = "controls-panel", **kwargs) -> PanelSpec:
    return PanelSpec(id=panel_id, kind="controls", **kwargs)


def view_3d_visual(window: VispyFrontendWindow, view_id: str, visual_key: str):
    return window._view_host(view_id).visual(visual_key)


def make_layout(title: str, *, panels: tuple[PanelSpec, ...]) -> LayoutSpec:
    main_row = tuple(panel.id for panel in panels if panel.kind != "controls")
    rows: list[tuple[str, ...]] = []
    if main_row:
        rows.append(main_row)
    rows.extend((panel.id,) for panel in panels if panel.kind == "controls")
    return LayoutSpec(title=title, panels=panels, panel_grid=tuple(rows))


def update_messages(*updates):
    return [update_message(update) for update in updates]


def float_control(control_id: str, label: str, default: float, min_value: float = 0.0, max_value: float = 1.0, steps: int = 100) -> ControlSpec:
    return ControlSpec(
        id=control_id,
        label=label,
        value_spec=ScalarValueSpec(default=default, min=min_value, max=max_value, value_type="float"),
        presentation=ControlPresentationSpec(kind="slider", steps=steps),
    )


def int_control(control_id: str, label: str, default: int, min_value: int = 0, max_value: int = 100) -> ControlSpec:
    return ControlSpec(
        id=control_id,
        label=label,
        value_spec=ScalarValueSpec(default=default, min=min_value, max=max_value, value_type="int"),
    )


def choice_control(control_id: str, label: str, default: str, options: tuple[str, ...]) -> ControlSpec:
    return ControlSpec(id=control_id, label=label, value_spec=ChoiceValueSpec(default=default, options=options))


def bool_control(control_id: str, label: str, default: bool) -> ControlSpec:
    return ControlSpec(id=control_id, label=label, value_spec=BoolValueSpec(default=default))


def resolved_controls_host(window: VispyFrontendWindow, panel_id: str = "controls-panel") -> ControlsHostPanel:
    return window.controls_host_panels[panel_id]


def resolved_controls_panel(window: VispyFrontendWindow, panel_id: str = "controls-panel") -> ControlsPanel:
    panel = window.controls_panel(panel_id)
    assert panel is not None
    return panel


def test_line_plot_panel_resolves_selected_entity_binding():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="voltage",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="trace",
        field_id=field.id,
        x_dim="time",
        selectors={"segment": StateBinding("selected_entity_id")},
        title="Voltage",
        x_label="Time",
        y_label="Voltage",
    )

    panel.refresh(view, field, {"selected_entity_id": "seg-b"})
    x_data, y_data = panel._plot_item.getData()
    assert np.allclose(x_data, np.array([0.0, 1.0, 2.0], dtype=np.float32))
    assert np.allclose(y_data, np.array([10.0, 20.0, 30.0], dtype=np.float32))
    assert panel.resolved_title == "Voltage"
    app.quit()


def test_line_plot_host_uses_resolved_plot_title():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotHostPanel(panel_id="trace-panel", view_id="trace", title="Trace")
    field = Field(
        id="voltage",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="trace",
        field_id=field.id,
        x_dim="time",
        selectors={"segment": StateBinding("selected_entity_id")},
        title="Voltage",
        x_label="Time",
        y_label="Voltage",
    )

    panel.refresh(view, field, {"selected_entity_id": "seg-b"})

    assert "Voltage" in panel.title()
    assert panel.line_plot_panel.plotItem.titleLabel.text == ""
    app.quit()


def test_line_plot_panel_enables_view_clipping_and_auto_downsampling():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()

    assert panel._plot_item.opts["clipToView"] is True
    assert panel._plot_item.opts["autoDownsample"] is True
    assert panel._plot_item.opts["downsampleMethod"] == "peak"
    assert panel._plot_item.opts["skipFiniteCheck"] is True
    app.quit()


def test_multi_series_line_plot_items_inherit_render_optimization_defaults():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="cascade",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("series", "time"),
        coords={
            "series": np.array(["ligand", "receptor"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="cascade-plot",
        field_id=field.id,
        x_dim="time",
        series_dim="series",
    )

    panel.refresh(view, field, {})

    for item in panel._series_items.values():
        assert item.opts["clipToView"] is True
        assert item.opts["autoDownsample"] is True
        assert item.opts["downsampleMethod"] == "peak"
        assert item.opts["skipFiniteCheck"] is True
    app.quit()


def build_surface_cross_section_app():
    x = np.linspace(-1.0, 1.0, 8, dtype=np.float32)
    y = np.linspace(-2.0, 2.0, 6, dtype=np.float32)
    values = (np.sin(x[None, :]) + np.cos(y[:, None])).astype(np.float32)
    field, geometry = grid_field(field_id="surface", values=values, x_coords=x, y_coords=y)
    controls = {
        "slice_axis": choice_control("slice_axis", "Slice axis", "x", ("x", "y")),
        "slice_position": float_control("slice_position", "Slice position", 0.0, 0.0, 1.0, 20),
    }
    operator = GridSliceOperatorSpec(
        id="surface-slice",
        field_id=field.id,
        geometry_id=geometry.id,
        axis_state_key="slice_axis",
        position_state_key="slice_position",
    )
    surface_view = SurfaceViewSpec(id="surface-view", field_id=field.id, geometry_id=geometry.id)
    line_view = LinePlotViewSpec(
        id="surface-line",
        operator_id=operator.id,
    )
    return build_surface_app(
        field=field,
        geometry=geometry,
        title="surface test",
        surface_view=surface_view,
        line_views=(line_view,),
        operators={operator.id: operator},
        controls=controls,
        panels=(
            view_3d_panel("surface-host", "surface-view", operator_ids=(operator.id,)),
            line_plot_panel_spec("surface-line-panel", "surface-line"),
            controls_panel_spec(),
        ),
        panel_grid=(("surface-host", "surface-line-panel"), ("controls-panel",)),
    )


def build_surface_axes_binding_app():
    x = np.linspace(-1.0, 1.0, 8, dtype=np.float32)
    y = np.linspace(-2.0, 2.0, 6, dtype=np.float32)
    values = (np.sin(x[None, :]) + np.cos(y[:, None])).astype(np.float32)
    field, geometry = grid_field(field_id="surface", values=values, x_coords=x, y_coords=y)
    controls = {
        "tick_count": int_control("tick_count", "Axis ticks", 7, 0, 12),
        "tick_label_size": float_control("tick_label_size", "Tick text size", 12.0, 6.0, 24.0, 18),
        "axis_label_size": float_control("axis_label_size", "Axis label size", 16.0, 8.0, 32.0, 24),
        "axis_color": choice_control("axis_color", "Axis color", "black", ("black", "red")),
        "text_color": choice_control("text_color", "Text color", "black", ("black", "blue")),
        "axis_alpha": float_control("axis_alpha", "Axis alpha", 1.0, 0.0, 1.0, 10),
    }
    surface_view = SurfaceViewSpec(
        id="surface-view",
        field_id=field.id,
        geometry_id=geometry.id,
        render_axes=True,
        axes_in_middle=True,
        tick_count=StateBinding("tick_count"),
        tick_label_size=StateBinding("tick_label_size"),
        axis_label_size=StateBinding("axis_label_size"),
        axis_color=StateBinding("axis_color"),
        text_color=StateBinding("text_color"),
        axis_alpha=StateBinding("axis_alpha"),
        axis_labels=("x", "y", "height"),
    )
    return build_surface_app(
        field=field,
        geometry=geometry,
        title="surface axes test",
        surface_view=surface_view,
        controls=controls,
        panels=(
            view_3d_panel("surface-host", "surface-view"),
            controls_panel_spec(),
        ),
        panel_grid=(("surface-host",), ("controls-panel",)),
    )


def test_refresh_planner_targets_slice_state_to_overlay_and_line_plot():
    app_spec = build_surface_cross_section_app()
    planner = RefreshPlanner(app_spec.app_spec)

    assert planner.targets_for_state_change("slice_position") == {
        RefreshTarget.operator_overlay("surface-view"),
        RefreshTarget.line_plot("surface-line"),
    }
    assert planner.targets_for_state_change("slice_axis") == {
        RefreshTarget.operator_overlay("surface-view"),
        RefreshTarget.line_plot("surface-line"),
    }


def test_refresh_planner_splits_surface_axis_geometry_and_style_targets():
    app_spec = build_surface_axes_binding_app()
    planner = RefreshPlanner(app_spec.app_spec)

    assert planner.targets_for_state_change("tick_count") == {
        RefreshTarget.surface_axes_geometry("surface-view"),
    }
    assert planner.targets_for_state_change("tick_label_size") == {
        RefreshTarget.surface_axes_style("surface-view"),
    }
    assert planner.targets_for_state_change("axis_color") == {
        RefreshTarget.surface_axes_style("surface-view"),
    }


def test_refresh_planner_targets_state_graph_fields():
    nodes = Field(
        id="state-occupancy",
        values=np.array([1.0, 0.0], dtype=np.float32),
        dims=("state",),
        coords={"state": np.array(["open", "closed"])},
    )
    edges = Field(
        id="state-transition",
        values=np.array([0.5], dtype=np.float32),
        dims=("edge",),
        coords={"edge": np.array(["open-to-closed"])},
    )
    view = StateGraphViewSpec(
        id="state-graph",
        node_field_id=nodes.id,
        edge_field_id=edges.id,
        node_positions=(("open", 0.2, 0.5), ("closed", 0.8, 0.5)),
        edges=(("open", "closed", "open-to-closed"),),
    )
    scene = AppSpec(
        fields={nodes.id: nodes, edges.id: edges},
        geometries={},
        views={view.id: view},
        layout=LayoutSpec(
            panels=(PanelSpec(id="state-graph-panel", kind="state_graph", view_ids=(view.id,)),),
        ),
    )
    planner = RefreshPlanner(scene)

    assert planner.full_refresh_targets() == {
        RefreshTarget.CONTROLS,
        RefreshTarget.state_graph("state-graph"),
    }
    assert planner.targets_for_field_replace(nodes.id) == {RefreshTarget.state_graph("state-graph")}
    assert planner.targets_for_field_replace(edges.id) == {RefreshTarget.state_graph("state-graph")}


def test_surface_control_change_avoids_surface_mesh_refresh():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = VispyFrontendWindow(build_surface_cross_section_app())
    window.timer.stop()
    surface_visual = view_3d_visual(window, "surface-view", SURFACE_3D_VISUAL_KEY)
    surface_visual.refresh_visual = Mock()
    surface_visual.refresh_axes_geometry = Mock()
    surface_visual.refresh_axes_style = Mock()
    surface_visual.refresh_operator_overlays = Mock()
    window.viewport.commit = Mock()
    window.line_plot_panel("surface-line").refresh = Mock()
    window._line_plot_last_refresh_s["surface-line"] = 10.0

    with patch.object(frontend_module.time, "monotonic", return_value=10.01):
        window._on_control_changed(window.app_spec.interactions.controls["slice_position"], 0.4)

    surface_visual.refresh_visual.assert_not_called()
    surface_visual.refresh_axes_geometry.assert_not_called()
    surface_visual.refresh_axes_style.assert_not_called()
    surface_visual.refresh_operator_overlays.assert_called_once()
    window.viewport.commit.assert_called_once()
    assert "surface-line" in window._dirty_line_plot_views
    window.line_plot_panel("surface-line").refresh.assert_not_called()
    window._flush_due_line_plot_refreshes(force=True)
    window.line_plot_panel("surface-line").refresh.assert_called_once()

    window.close()
    app.quit()


def test_scalar_control_state_default_comes_from_value_spec():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scene = AppSpec(
        fields={},
        geometries={},
        views={},
        controls={"gain": float_control("gain", "Gain", 1.25, 0.0, 2.0)},
        layout=make_layout("Scalar default", panels=(controls_panel_spec(control_ids=("gain",)),)),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Scalar default"))
    window.timer.stop()

    assert window.state["gain"] == 1.25

    window.close()
    app.quit()


def test_controls_panel_renders_widgets_from_value_spec_and_presentation():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = ControlsPanel(lambda *_args: None)
    controls = [
        float_control("gain", "Gain", 0.5, 0.0, 1.0, 12),
        int_control("count", "Count", 3, 0, 9),
        choice_control("mode", "Mode", "a", ("a", "b")),
        bool_control("enabled", "Enabled", True),
    ]

    panel.set_controls(controls, [], {})

    assert isinstance(panel.widgets["gain"], QtWidgets.QSlider)
    assert isinstance(panel.widgets["count"], QtWidgets.QSpinBox)
    assert isinstance(panel.widgets["mode"], QtWidgets.QComboBox)
    assert isinstance(panel.widgets["enabled"], QtWidgets.QCheckBox)

    panel.close()
    app.quit()


def test_log_scaled_float_control_initializes_slider_from_default_value():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = ControlsPanel(lambda *_args: None)
    control = ControlSpec(
        id="effector_k",
        label="Effector K",
        value_spec=ScalarValueSpec(default=0.5, min=0.001, max=10.0, value_type="float"),
        presentation=ControlPresentationSpec(kind="slider", steps=100, scale="log"),
    )

    panel.set_controls([control], [], {})

    slider = panel.widgets["effector_k"]
    assert isinstance(slider, QtWidgets.QSlider)
    expected = ControlsPanel._slider_value_to_raw(
        0.5,
        min_value=0.001,
        max_value=10.0,
        steps=100,
        scale="log",
    )
    assert slider.value() == expected

    resolved = ControlsPanel._slider_raw_to_value(
        slider.value(),
        min_value=0.001,
        max_value=10.0,
        steps=100,
        scale="log",
    )
    assert resolved == pytest.approx(0.5, rel=0.05)

    panel.close()
    app.quit()


def test_xy_control_uses_atomic_state_key_and_single_session_command():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    xy_control = ControlSpec(
        id="stimulus_position",
        label="Stimulus position",
        value_spec=XYValueSpec(default={"x": 0.5, "y": 0.25}, x_range=(0.0, 1.0), y_range=(0.0, 1.0)),
        presentation=ControlPresentationSpec(kind="xy_pad", shape="square"),
        send_to_backend=True,
    )
    scene = AppSpec(
        fields={},
        geometries={},
        views={},
        controls={xy_control.id: xy_control},
        layout=make_layout("XY control", panels=(controls_panel_spec(control_ids=(xy_control.id,)),)),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="XY control"))
    window.timer.stop()
    window.transport = Mock()
    window.refresh_planner = Mock()
    window.refresh_planner.targets_for_state_change.return_value = set()
    new_value = {"x": 0.2, "y": 0.8}

    assert window.state["stimulus_position"] == {"x": 0.5, "y": 0.25}
    assert "x" not in window.state
    assert "y" not in window.state

    window._on_control_changed(xy_control, new_value)

    assert window.state["stimulus_position"] == new_value
    window.transport.send.assert_called_once()
    command = window.transport.send.call_args[0][0].payload
    assert isinstance(command, SetControl)
    assert command.control_id == "stimulus_position"
    assert command.value == new_value
    window.refresh_planner.targets_for_state_change.assert_called_once_with("stimulus_position")

    window.close()
    app.quit()


def test_field_replace_with_identical_coords_does_not_refresh_surface_axes_geometry():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app_spec = build_surface_cross_section_app()
    app_spec.app_spec.replace_view("surface-view", {"color_limits": (0.0, 2.0)})
    window = VispyFrontendWindow(app_spec)
    window.timer.stop()
    field = window.app_spec.data.fields["surface"]
    original_x_coord = field.coords["x"]
    original_y_coord = field.coords["y"]
    surface_visual = view_3d_visual(window, "surface-view", SURFACE_3D_VISUAL_KEY)
    surface_visual.refresh_visual = Mock()
    surface_visual.refresh_axes_geometry = Mock()
    surface_visual.refresh_operator_overlays = Mock()
    window.viewport.commit = Mock()
    window._view_3d_last_refresh_s.clear()
    window.transport = Mock()
    window.transport.poll.return_value = update_messages(
        FieldReplace(
            field_id="surface",
            values=np.ones_like(field.values),
            coords={dim: coord.copy() for dim, coord in field.coords.items()},
        )
    )

    window._poll_transport()

    surface_visual.refresh_visual.assert_called_once()
    surface_visual.refresh_axes_geometry.assert_not_called()
    assert window.app_spec.data.fields["surface"].coords["x"] is original_x_coord
    assert window.app_spec.data.fields["surface"].coords["y"] is original_y_coord

    window.close()
    app.quit()


def test_surface_axis_style_control_change_avoids_geometry_refresh():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = VispyFrontendWindow(build_surface_axes_binding_app())
    window.timer.stop()
    surface_visual = view_3d_visual(window, "surface-view", SURFACE_3D_VISUAL_KEY)
    surface_visual.refresh_visual = Mock()
    surface_visual.refresh_axes_geometry = Mock()
    surface_visual.refresh_axes_style = Mock()
    surface_visual.refresh_operator_overlays = Mock()
    window.viewport.commit = Mock()

    window._on_control_changed(window.app_spec.interactions.controls["tick_label_size"], 18.0)

    surface_visual.refresh_visual.assert_not_called()
    surface_visual.refresh_axes_geometry.assert_not_called()
    surface_visual.refresh_axes_style.assert_called_once()
    surface_visual.refresh_operator_overlays.assert_not_called()
    window.viewport.commit.assert_called_once()

    window.close()
    app.quit()


def test_surface_slice_overlay_moves_with_control_changes():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = VispyFrontendWindow(build_surface_cross_section_app())
    window.timer.stop()

    surface_visual = view_3d_visual(window, "surface-view", SURFACE_3D_VISUAL_KEY)
    overlay = surface_visual.renderer._slice_overlays["surface-slice"]
    initial_pos = np.array(overlay._line._pos, copy=True)
    window._on_control_changed(window.app_spec.interactions.controls["slice_position"], 1.0)
    overlay = surface_visual.renderer._slice_overlays["surface-slice"]
    moved_pos = np.array(overlay._line._pos, copy=True)
    window._on_control_changed(window.app_spec.interactions.controls["slice_axis"], "y")
    overlay = surface_visual.renderer._slice_overlays["surface-slice"]
    axis_switched_pos = np.array(overlay._line._pos, copy=True)

    assert not np.allclose(initial_pos, moved_pos)
    assert not np.allclose(moved_pos, axis_switched_pos)

    window.close()
    app.quit()


def test_surface_visual_reuses_same_surface_object_for_same_shape_updates():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = Viewport3DPanel()
    surface_visual = Surface3DVisual(panel.view)
    x = np.linspace(-1.0, 1.0, 8, dtype=np.float32)
    y = np.linspace(-2.0, 2.0, 6, dtype=np.float32)
    values = (np.sin(x[None, :]) + np.cos(y[:, None])).astype(np.float32)
    field, geometry = grid_field(field_id="surface", values=values, x_coords=x, y_coords=y)
    view = SurfaceViewSpec(id="surface-view", field_id=field.id, geometry_id=geometry.id)
    state = {
        "surface-view:color_map": "bwr",
        "surface-view:color_limits": None,
        "surface-view:color_by": "height",
        "surface-view:surface_color": (0.5, 0.6, 0.8, 1.0),
        "surface-view:surface_shading": "unlit",
        "surface-view:surface_alpha": 1.0,
        "surface-view:background_color": "white",
    }

    surface_visual.refresh_visual(surface_view=view, surface_field=field, grid_geometry=geometry, resolved_state=state)
    first_surface = surface_visual.renderer.surface

    surface_visual.refresh_visual(
        surface_view=view,
        surface_field=field.with_values(field.values + 1.0),
        grid_geometry=geometry,
        resolved_state=state,
    )
    second_surface = surface_visual.renderer.surface

    assert first_surface is second_surface
    app.quit()


def test_viewport_3d_panel_mounts_generic_visuals():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = Viewport3DPanel()
    first = SimpleNamespace(clear=Mock(), pick_entity=Mock(return_value=None))
    second = SimpleNamespace(clear=Mock(), pick_entity=Mock(return_value=None))
    third = SimpleNamespace(clear=Mock(), pick_entity=Mock(return_value=None))

    panel.mount_visual("first", first)
    panel.mount_visual("second", second)
    panel.mount_visual("third", third)
    with pytest.raises(ValueError, match="already mounted"):
        panel.mount_visual("third", third)
    with pytest.raises(ValueError, match="Unknown 3D visual"):
        panel.activate_visual("missing")

    panel.activate_visual("first")
    assert panel.active_visual_key == "first"
    first.clear.assert_not_called()
    second.clear.assert_not_called()

    panel.activate_visual("second")
    assert panel.active_visual_key == "second"
    first.clear.assert_called_once()
    second.clear.assert_not_called()

    panel.activate_visual("third")
    assert panel.active_visual_key == "third"
    second.clear.assert_called_once()
    third.clear.assert_not_called()

    panel.clear()
    assert panel.active_visual_key is None
    assert first.clear.call_count == 2
    assert second.clear.call_count == 2
    third.clear.assert_called_once()
    app.quit()


def test_surface_axes_overlay_reuses_visual_objects_for_style_refresh():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = Viewport3DPanel()
    surface_visual = Surface3DVisual(panel.view)
    x = np.linspace(-1.0, 1.0, 8, dtype=np.float32)
    y = np.linspace(-2.0, 2.0, 6, dtype=np.float32)
    values = (np.sin(x[None, :]) + np.cos(y[:, None])).astype(np.float32)
    field, geometry = grid_field(field_id="surface", values=values, x_coords=x, y_coords=y)
    view = SurfaceViewSpec(
        id="surface-view",
        field_id=field.id,
        geometry_id=geometry.id,
        render_axes=True,
        axes_in_middle=True,
        tick_count=7,
        tick_label_size=12.0,
        axis_label_size=16.0,
        axis_color="black",
        text_color="black",
        axis_alpha=1.0,
        axis_labels=("x", "y", "height"),
    )
    state = {
        "surface-view:color_map": "bwr",
        "surface-view:color_limits": None,
        "surface-view:color_by": "height",
        "surface-view:surface_color": (0.5, 0.6, 0.8, 1.0),
        "surface-view:surface_shading": "unlit",
        "surface-view:surface_alpha": 1.0,
        "surface-view:background_color": "white",
        "surface-view:render_axes": True,
        "surface-view:axes_in_middle": True,
        "surface-view:tick_count": 7,
        "surface-view:tick_length_scale": 1.0,
        "surface-view:tick_label_size": 12.0,
        "surface-view:axis_label_size": 16.0,
        "surface-view:axis_color": "black",
        "surface-view:text_color": "black",
        "surface-view:axis_alpha": 1.0,
    }

    surface_visual.refresh_visual(surface_view=view, surface_field=field, grid_geometry=geometry, resolved_state=state)
    surface_visual.refresh_axes_geometry(surface_view=view, resolved_state=state)
    overlay = surface_visual.renderer.axes
    visuals = {
        "axis_lines": overlay._axis_lines,
        "tick_lines": overlay._tick_lines,
        "x_ticks": overlay._tick_labels["x"],
        "y_ticks": overlay._tick_labels["y"],
        "z_ticks": overlay._tick_labels["z"],
        "x_label": overlay._axis_labels["x"],
        "y_label": overlay._axis_labels["y"],
        "z_label": overlay._axis_labels["z"],
    }

    style_state = dict(state)
    style_state["surface-view:tick_label_size"] = 18.0
    style_state["surface-view:axis_label_size"] = 22.0
    style_state["surface-view:axis_color"] = "red"
    style_state["surface-view:text_color"] = "blue"
    style_state["surface-view:axis_alpha"] = 0.5
    surface_visual.refresh_axes_style(surface_view=view, resolved_state=style_state)

    assert overlay._axis_lines is visuals["axis_lines"]
    assert overlay._tick_lines is visuals["tick_lines"]
    assert overlay._tick_labels["x"] is visuals["x_ticks"]
    assert overlay._tick_labels["y"] is visuals["y_ticks"]
    assert overlay._tick_labels["z"] is visuals["z_ticks"]
    assert overlay._axis_labels["x"] is visuals["x_label"]
    assert overlay._axis_labels["y"] is visuals["y_label"]
    assert overlay._axis_labels["z"] is visuals["z_label"]
    assert overlay._tick_labels["x"].font_size == 18.0
    assert overlay._axis_labels["x"].font_size == 22.0

    app.quit()


def test_viewport_3d_panel_applies_host_camera_settings():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = view_3d_panel(
        "surface-host",
        "surface-view",
        camera_distance=90.0,
        camera_elevation=20.0,
        camera_azimuth=15.0,
    )

    panel = Viewport3DPanel(host_spec=host)

    assert panel.view.camera.distance == 90.0
    assert panel.view.camera.elevation == 20.0
    assert panel.view.camera.azimuth == 15.0
    app.quit()


def test_build_surface_app_accepts_custom_3d_hosts():
    x = np.linspace(-1.0, 1.0, 8, dtype=np.float32)
    y = np.linspace(-1.0, 1.0, 6, dtype=np.float32)
    values = (np.sin(x[None, :]) + np.cos(y[:, None])).astype(np.float32)
    field, geometry = grid_field(field_id="surface", values=values, x_coords=x, y_coords=y)
    surface_view = SurfaceViewSpec(id="surface-view", field_id=field.id, geometry_id=geometry.id)
    host = view_3d_panel(
        "surface-host",
        "surface-view",
        camera_distance=85.0,
        camera_elevation=25.0,
        camera_azimuth=5.0,
    )

    app_spec = build_surface_app(
        field=field,
        geometry=geometry,
        surface_view=surface_view,
        panels=(host,),
        panel_grid=(("surface-host",),),
    )

    assert app_spec.app_spec is not None
    assert app_spec.app_spec.active_layout().panels == (host,)


def test_build_surface_app_accepts_multiple_line_views():
    x = np.linspace(-1.0, 1.0, 8, dtype=np.float32)
    y = np.linspace(-1.0, 1.0, 6, dtype=np.float32)
    values = (np.sin(x[None, :]) + np.cos(y[:, None])).astype(np.float32)
    field, geometry = grid_field(field_id="surface", values=values, x_coords=x, y_coords=y)
    surface_view = SurfaceViewSpec(id="surface-view", field_id=field.id, geometry_id=geometry.id)
    line_views = (
        LinePlotViewSpec(id="surface-line-x", field_id=field.id, x_dim="x", selectors={"y": 0}),
        LinePlotViewSpec(id="surface-line-y", field_id=field.id, x_dim="y", selectors={"x": 0}),
    )

    app_spec = build_surface_app(
        field=field,
        geometry=geometry,
        surface_view=surface_view,
        line_views=line_views,
    )

    assert app_spec.app_spec is not None
    assert tuple(
        panel.view_ids[0]
        for panel in app_spec.app_spec.active_layout().panels
        if panel.kind == "line_plot"
    ) == ("surface-line-x", "surface-line-y")


def test_morphology_renderer_uses_fixed_clim_without_dynamic_recaling():
    renderer = MorphologyRenderer.__new__(MorphologyRenderer)
    renderer.collection = Mock()
    renderer._color_buf = np.zeros((2, 4), dtype=np.float32)

    renderer.update_colors(np.array([5.0, 6.0], dtype=np.float32), "scalar", color_limits=(0.0, 10.0))

    colors = renderer.collection.set_colors.call_args.args[0]
    assert np.allclose(colors[:, 0], np.array([0.5, 0.6], dtype=np.float32))
    assert np.allclose(colors[:, 2], np.array([0.5, 0.4], dtype=np.float32))


def test_morphology_renderer_supports_single_color_ramp_maps():
    renderer = MorphologyRenderer.__new__(MorphologyRenderer)
    renderer.collection = Mock()
    renderer._color_buf = np.zeros((2, 4), dtype=np.float32)

    renderer.update_colors(np.array([0.0, 1.0], dtype=np.float32), "ramp:#f18f01", color_limits=(0.0, 1.0))

    colors = renderer.collection.set_colors.call_args.args[0]
    target = np.array([0xF1 / 255.0, 0x8F / 255.0, 0x01 / 255.0, 1.0], dtype=np.float32)
    low = target.copy()
    low[:3] = 1.0 - 0.2 * (1.0 - target[:3])
    assert np.allclose(colors[0], low)
    assert np.allclose(colors[1], target)


def test_morphology_renderer_supports_two_color_ramp_maps():
    renderer = MorphologyRenderer.__new__(MorphologyRenderer)
    renderer.collection = Mock()
    renderer._color_buf = np.zeros((2, 4), dtype=np.float32)

    renderer.update_colors(
        np.array([0.0, 1.0], dtype=np.float32),
        "ramp:#245aa8:#9e2a2b",
        color_limits=(0.0, 1.0),
    )

    colors = renderer.collection.set_colors.call_args.args[0]
    low = np.array([0x24 / 255.0, 0x5A / 255.0, 0xA8 / 255.0, 1.0], dtype=np.float32)
    high = np.array([0x9E / 255.0, 0x2A / 255.0, 0x2B / 255.0, 1.0], dtype=np.float32)
    assert np.allclose(colors[0], low)
    assert np.allclose(colors[1], high)


def test_morphology_renderer_supports_matplotlib_named_maps():
    matplotlib = pytest.importorskip("matplotlib")

    renderer = MorphologyRenderer.__new__(MorphologyRenderer)
    renderer.collection = Mock()
    renderer._color_buf = np.zeros((2, 4), dtype=np.float32)

    renderer.update_colors(np.array([0.0, 1.0], dtype=np.float32), "mpl:viridis", color_limits=(0.0, 1.0))

    colors = renderer.collection.set_colors.call_args.args[0]
    expected = np.asarray(matplotlib.colormaps["viridis"](np.array([0.0, 1.0], dtype=np.float32)), dtype=np.float32)
    assert np.allclose(colors, expected)


def test_morphology_renderer_supports_matplotlib_ramp_maps():
    pytest.importorskip("matplotlib")
    from matplotlib.colors import LinearSegmentedColormap

    renderer = MorphologyRenderer.__new__(MorphologyRenderer)
    renderer.collection = Mock()
    renderer._color_buf = np.zeros((2, 4), dtype=np.float32)

    renderer.update_colors(
        np.array([0.0, 1.0], dtype=np.float32),
        "mpl-ramp:#245aa8:#9e2a2b",
        color_limits=(0.0, 1.0),
    )

    colors = renderer.collection.set_colors.call_args.args[0]
    expected_cmap = LinearSegmentedColormap.from_list(
        "compneurovis-test-ramp",
        ["#245aa8", "#9e2a2b"],
    )
    expected = np.asarray(expected_cmap(np.array([0.0, 1.0], dtype=np.float32)), dtype=np.float32)
    assert np.allclose(colors, expected)


def test_state_graph_panel_colormap_broadcasts_multiple_values():
    panel = StateGraphPanel.__new__(StateGraphPanel)

    colors = panel._apply_cmap(
        np.array([-0.1, 0.0, 0.1], dtype=np.float32),
        "bwr",
        (-0.1, 0.1),
    )

    assert colors.shape == (3, 4)
    assert colors.dtype == np.float32
    assert np.all(np.isfinite(colors))


def test_state_graph_label_color_contrasts_node_fill():
    assert _state_label_color_for_fill(np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)) == (1.0, 1.0, 1.0, 1.0)
    assert _state_label_color_for_fill(np.array([1.0, 0.9, 0.1, 1.0], dtype=np.float32)) == (0.0, 0.0, 0.0, 1.0)


def test_state_graph_fire_nodes_use_white_to_deep_red_ramp():
    panel = StateGraphPanel.__new__(StateGraphPanel)

    colors = panel._apply_cmap(
        np.array([0.0, 1.0], dtype=np.float32),
        _state_node_colormap_name("fire"),
        (0.0, 1.0),
    )

    assert np.allclose(colors[0], np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32))
    assert colors[1, 0] > colors[1, 1]
    assert colors[1, 1] > colors[1, 2]
    assert colors[1, 3] == 1.0


def test_state_graph_panel_reuses_field_index_cache():
    panel = StateGraphPanel.__new__(StateGraphPanel)
    panel._field_index_cache = {}
    field = Field(
        id="state_nodes",
        values=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        dims=("state",),
        coords={"state": np.array(["A", "B", "C"])},
    )

    first = panel._read_field_values(field, ["C", "A", "missing"], "state")
    field2 = field.with_values(np.array([1.0, 2.0, 3.0], dtype=np.float32))
    second = panel._read_field_values(field2, ["C", "A", "missing"], "state")

    assert len(panel._field_index_cache) == 1
    assert np.allclose(first, [0.3, 0.1, 0.0])
    assert np.allclose(second, [3.0, 1.0, 0.0])


def test_run_app_skips_frontend_launch_in_spawned_child():
    original_current_process = frontend_module.mp.current_process
    original_qapplication = frontend_module.QtWidgets.QApplication
    try:
        frontend_module.mp.current_process = lambda: SimpleNamespace(name="SpawnProcess-1")
        frontend_module.QtWidgets.QApplication = Mock()
        frontend_module.run_app(frontend_module.RunSpec())
        frontend_module.QtWidgets.QApplication.assert_not_called()
    finally:
        frontend_module.mp.current_process = original_current_process
        frontend_module.QtWidgets.QApplication = original_qapplication


def test_frontend_shows_modal_for_fatal_session_error():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class FakeTransport:
        def __init__(self):
            self._dead = True
            self.calls = 0

        def poll(self):
            if self.calls == 0:
                self.calls += 1
                return update_messages(Error("Traceback (most recent call last):\nRuntimeError: boom"))
            return []

        def poll_bootstrap(self):
            return None

        def stop(self):
            return None

    window = VispyFrontendWindow(RunSpec(title="Error test"))
    window.timer.stop()
    window.transport = FakeTransport()

    original_critical = frontend_module.QtWidgets.QMessageBox.critical
    original_stderr = frontend_module.sys.stderr
    frontend_module.QtWidgets.QMessageBox.critical = Mock()
    frontend_module.sys.stderr = io.StringIO()
    try:
        window._poll_transport()

        frontend_module.QtWidgets.QMessageBox.critical.assert_called_once()
        args = frontend_module.QtWidgets.QMessageBox.critical.call_args[0]
        assert args[1] == "Backend error"
        assert "RuntimeError: boom" in args[2]
        assert "RuntimeError: boom" in frontend_module.sys.stderr.getvalue()
        assert window.transport is None
        assert not window.timer.isActive()
    finally:
        frontend_module.QtWidgets.QMessageBox.critical = original_critical
        frontend_module.sys.stderr = original_stderr
        window.close()
        app.quit()


def test_frontend_shows_loading_state_before_first_scene():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = VispyFrontendWindow(RunSpec(title="Loading test"))
    window.timer.stop()

    assert window._stack.currentWidget() is window._loading_label
    assert window._loading_label.text() == "Loading visualization..."

    window.close()
    app.quit()


def test_frontend_uses_session_startup_scene_before_worker_ready(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class BootstrapBackend(BackendBase):
        def build_startup_app_spec(self):
            field = Field(
                id="bootstrap",
                values=np.array([[0.0]], dtype=np.float32),
                dims=("series", "time"),
                coords={
                    "series": np.array(["demo"]),
                    "time": np.array([0.0], dtype=np.float32),
                },
            )
            view = LinePlotViewSpec(
                id="bootstrap-view",
                field_id="bootstrap",
                x_dim="time",
                series_dim="series",
                title="Bootstrap",
                x_label="Time",
                y_label="Value",
            )
            return AppSpec(
                fields={"bootstrap": field},
                geometries={},
                views={"bootstrap-view": view},
                layout=make_layout(
                    "Bootstrap",
                    panels=(line_plot_panel_spec("bootstrap-view-panel", "bootstrap-view"),),
                ),
            )

        def initialize(self, app_spec):
            pass

        def update(self) -> None:
            return None

        def handle(self, message) -> None:
            return None

    class FakeTransport:
        def __init__(self, backend, provided_app_spec, diagnostics=None, parent=None):
            self.backend = backend
            self.provided_app_spec = provided_app_spec
            self.diagnostics = diagnostics
            self.parent = parent
            self._dead = False
            self._bootstrap_app_spec = None

        def start(self):
            if self.provided_app_spec is None:
                instance = self.backend()
                self._bootstrap_app_spec = instance.build_startup_app_spec()

        def stop(self):
            return None

        def poll(self):
            return []

        def poll_bootstrap(self):
            result = self._bootstrap_app_spec
            self._bootstrap_app_spec = None
            return result

    monkeypatch.setattr(frontend_module, "PipeTransport", FakeTransport)

    diagnostics = DiagnosticsSpec(perf_log_enabled=True)
    window = VispyFrontendWindow(RunSpec(backend=BootstrapBackend, title="Bootstrap test", diagnostics=diagnostics))
    window.timer.stop()

    assert isinstance(window.transport, FakeTransport)
    assert window.transport.backend is BootstrapBackend
    assert window.transport.diagnostics == diagnostics
    assert window.app_spec is None
    assert window._stack.currentWidget() is window._loading_label

    window._poll_transport()

    assert window.app_spec is not None
    assert window.app_spec.active_layout().panel("bootstrap-view-panel") is not None
    assert window._stack.currentWidget() is window._layout_splitter

    window.close()
    app.quit()


def test_frontend_logs_nonfatal_session_error_to_stderr_without_modal():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class FakeTransport:
        def __init__(self):
            self._dead = False
            self.calls = 0

        def poll(self):
            if self.calls == 0:
                self.calls += 1
                return update_messages(Error("Nonfatal backend warning"))
            return []

        def poll_bootstrap(self):
            return None

        def stop(self):
            return None

    window = VispyFrontendWindow(RunSpec(title="Nonfatal error test"))
    window.timer.stop()
    window.transport = FakeTransport()

    original_critical = frontend_module.QtWidgets.QMessageBox.critical
    original_stderr = frontend_module.sys.stderr
    frontend_module.QtWidgets.QMessageBox.critical = Mock()
    frontend_module.sys.stderr = io.StringIO()
    try:
        window._poll_transport()

        frontend_module.QtWidgets.QMessageBox.critical.assert_not_called()
        assert "Nonfatal backend warning" in frontend_module.sys.stderr.getvalue()
        assert window.transport is not None
        assert window.statusBar().currentMessage() == "Nonfatal backend warning"
    finally:
        frontend_module.QtWidgets.QMessageBox.critical = original_critical
        frontend_module.sys.stderr = original_stderr
        window.close()
        app.quit()


def test_build_neuron_app_accepts_session_class():
    class DummyNeuronBackend(NeuronBackend):
        def build_sections(self):
            return []

        def initialize(self, app_spec):
            raise AssertionError("should not initialize during app construction")

        def update(self) -> None:
            return None

        def handle(self, message) -> None:
            command = message.payload
            return None

    run_spec = build_neuron_app(DummyNeuronBackend, title="Dummy")

    assert run_spec.backend is DummyNeuronBackend
    assert run_spec.interaction_target is None
    assert run_spec.title == "Dummy"


def test_build_neuron_app_requires_lazy_session_source():
    class DefaultInteractionBackend(NeuronBackend):
        def __init__(self):
            super().__init__(title="Default Interaction")

        def build_sections(self):
            return []

        def initialize(self, app_spec):
            raise AssertionError("should not initialize during app construction")

        def update(self) -> None:
            return None

        def handle(self, message) -> None:
            command = message.payload
            return None

    with pytest.raises(TypeError, match="requires a Backend subclass or top-level zero-argument factory"):
        build_neuron_app(DefaultInteractionBackend())


def test_build_neuron_app_supports_explicit_interaction_target_factory():
    class DefaultInteractionBackend(NeuronBackend):
        def __init__(self):
            super().__init__(title="Default Interaction")

        def build_sections(self):
            return []

        def initialize(self, app_spec):
            raise AssertionError("should not initialize during app construction")

        def update(self) -> None:
            return None

        def handle(self, message) -> None:
            command = message.payload
            return None

    class DummyInteractionTarget:
        def __init__(self):
            self.marker = "frontend-target"

    app_spec = build_neuron_app(DefaultInteractionBackend, interaction_target=DummyInteractionTarget)

    assert app_spec.interaction_target is DummyInteractionTarget
    resolved = resolve_interaction_target_source(app_spec.interaction_target)
    assert isinstance(resolved, DummyInteractionTarget)
    assert resolved.marker == "frontend-target"


def test_line_plot_panel_supports_multi_series_fields():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="cascade",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("series", "time"),
        coords={
            "series": np.array(["ligand", "receptor"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="cascade-plot",
        field_id=field.id,
        x_dim="time",
        series_dim="series",
        title="Cascade",
        x_label="Time",
        y_label="Value",
        colors={"ligand": "#ff0000", "receptor": "#0000ff"},
    )

    panel.refresh(view, field, {})

    assert set(panel._series_items.keys()) == {"ligand", "receptor"}
    ligand_x, ligand_y = panel._series_items["ligand"].getData()
    receptor_x, receptor_y = panel._series_items["receptor"].getData()
    assert np.allclose(ligand_x, np.array([0.0, 1.0, 2.0], dtype=np.float32))
    assert np.allclose(ligand_y, np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(receptor_x, np.array([0.0, 1.0, 2.0], dtype=np.float32))
    assert np.allclose(receptor_y, np.array([10.0, 20.0, 30.0], dtype=np.float32))
    app.quit()


def test_frontend_applies_state_patch_and_refreshes_bound_plot():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0, 2.0], [10.0, 20.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0, 1.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="trace",
        field_id="voltage",
        x_dim="time",
        selectors={"segment": StateBinding("selected_trace_entity_ids")},
        series_dim="segment",
    )
    scene = AppSpec(
        fields={"voltage": field},
        geometries={},
        views={"trace": view},
        layout=make_layout(
            "State patch test",
            panels=(line_plot_panel_spec("trace-panel", "trace"),),
        ),
    )

    class FakeTransport:
        _dead = False

        def poll(self):
            updates = update_messages(StatePatch({"selected_trace_entity_ids": ["seg-b"]}))
            self.poll = lambda: []
            return updates

        def stop(self):
            return None

    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="State patch test"))
    window.timer.stop()
    window.transport = FakeTransport()

    window._poll_transport()

    assert window.state["selected_trace_entity_ids"] == ["seg-b"]
    assert "trace" in window._dirty_line_plot_views
    window._flush_due_line_plot_refreshes(force=True)
    assert "seg-b" in window.line_plot_panel("trace")._series_items
    window.close()
    app.quit()


def test_frontend_can_render_multiple_line_plot_panels():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="signals",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("series", "time"),
        coords={
            "series": np.array(["a", "b"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    views = {
        "trace-a": LinePlotViewSpec(
            id="trace-a",
            field_id="signals",
            x_dim="time",
            selectors={"series": "a"},
            title="Trace A",
        ),
        "trace-b": LinePlotViewSpec(
            id="trace-b",
            field_id="signals",
            x_dim="time",
            selectors={"series": "b"},
            title="Trace B",
        ),
    }
    scene = AppSpec(
        fields={"signals": field},
        geometries={},
        views=views,
        layout=make_layout(
            "Multi plot",
            panels=(
                line_plot_panel_spec("trace-a-panel", "trace-a"),
                line_plot_panel_spec("trace-b-panel", "trace-b"),
            ),
        ),
    )

    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Multi plot"))
    window.timer.stop()

    assert tuple(window.line_plot_panels.keys()) == ("trace-a-panel", "trace-b-panel")
    x_a, y_a = window.line_plot_panel("trace-a")._plot_item.getData()
    x_b, y_b = window.line_plot_panel("trace-b")._plot_item.getData()
    assert np.allclose(x_a, np.array([0.0, 1.0, 2.0], dtype=np.float32))
    assert np.allclose(y_a, np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(x_b, np.array([0.0, 1.0, 2.0], dtype=np.float32))
    assert np.allclose(y_b, np.array([10.0, 20.0, 30.0], dtype=np.float32))

    window.close()
    app.quit()


def test_refresh_planner_targets_only_matching_line_plot_view_for_field_replace():
    scene = AppSpec(
        fields={
            "field-a": Field(
                id="field-a",
                values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
                dims=("time",),
                coords={"time": np.array([0.0, 1.0, 2.0], dtype=np.float32)},
            ),
            "field-b": Field(
                id="field-b",
                values=np.array([10.0, 20.0, 30.0], dtype=np.float32),
                dims=("time",),
                coords={"time": np.array([0.0, 1.0, 2.0], dtype=np.float32)},
            ),
        },
        geometries={},
        views={
            "trace-a": LinePlotViewSpec(id="trace-a", field_id="field-a", x_dim="time"),
            "trace-b": LinePlotViewSpec(id="trace-b", field_id="field-b", x_dim="time"),
        },
        layout=make_layout(
            "Multi planner",
            panels=(
                line_plot_panel_spec("trace-a-panel", "trace-a"),
                line_plot_panel_spec("trace-b-panel", "trace-b"),
            ),
        ),
    )
    planner = RefreshPlanner(scene)

    assert planner.targets_for_field_replace("field-a") == {RefreshTarget.line_plot("trace-a")}
    assert planner.targets_for_field_replace("field-b") == {RefreshTarget.line_plot("trace-b")}


def test_frontend_defers_line_plot_refresh_until_refresh_budget_allows():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scene = AppSpec(
        fields={
            "trace": Field(
                id="trace",
                values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
                dims=("time",),
                coords={"time": np.array([0.0, 1.0, 2.0], dtype=np.float32)},
            ),
        },
        geometries={},
        views={"trace": LinePlotViewSpec(id="trace", field_id="trace", x_dim="time")},
        layout=make_layout(
            "Deferred line plot",
            panels=(line_plot_panel_spec("trace-panel", "trace"),),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Deferred line plot"))
    window.timer.stop()
    host = window.line_plot_host_panels["trace-panel"]
    host.refresh = Mock()
    window._line_plot_last_refresh_s["trace"] = 10.0

    with patch.object(frontend_module.time, "monotonic", return_value=10.01):
        window._apply_refresh_targets({RefreshTarget.line_plot("trace")})

    host.refresh.assert_not_called()
    assert "trace" in window._dirty_line_plot_views

    with patch.object(frontend_module.time, "monotonic", return_value=10.11):
        window._flush_due_line_plot_refreshes()

    host.refresh.assert_called_once()
    assert "trace" not in window._dirty_line_plot_views
    window.close()
    app.quit()


def test_frontend_can_force_line_plot_refresh_despite_budget():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scene = AppSpec(
        fields={
            "trace": Field(
                id="trace",
                values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
                dims=("time",),
                coords={"time": np.array([0.0, 1.0, 2.0], dtype=np.float32)},
            ),
        },
        geometries={},
        views={"trace": LinePlotViewSpec(id="trace", field_id="trace", x_dim="time")},
        layout=make_layout(
            "Forced line plot",
            panels=(line_plot_panel_spec("trace-panel", "trace"),),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Forced line plot"))
    window.timer.stop()
    host = window.line_plot_host_panels["trace-panel"]
    host.refresh = Mock()
    window._line_plot_last_refresh_s["trace"] = 10.0

    with patch.object(frontend_module.time, "monotonic", return_value=10.01):
        window._apply_refresh_targets({RefreshTarget.line_plot("trace")}, force_line_plots=True)

    host.refresh.assert_called_once()
    assert "trace" not in window._dirty_line_plot_views
    window.close()
    app.quit()


def test_line_plot_view_can_opt_out_of_frontend_refresh_throttle():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scene = AppSpec(
        fields={
            "trace": Field(
                id="trace",
                values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
                dims=("time",),
                coords={"time": np.array([0.0, 1.0, 2.0], dtype=np.float32)},
            ),
        },
        geometries={},
        views={
            "trace": LinePlotViewSpec(
                id="trace",
                field_id="trace",
                x_dim="time",
                max_refresh_hz=0.0,
            )
        },
        layout=make_layout(
            "Unthrottled line plot",
            panels=(line_plot_panel_spec("trace-panel", "trace"),),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Unthrottled line plot"))
    window.timer.stop()
    host = window.line_plot_host_panels["trace-panel"]
    host.refresh = Mock()
    window._line_plot_last_refresh_s["trace"] = 10.0

    with patch.object(frontend_module.time, "monotonic", return_value=10.01):
        window._apply_refresh_targets({RefreshTarget.line_plot("trace")})

    host.refresh.assert_called_once()
    assert "trace" not in window._dirty_line_plot_views
    window.close()
    app.quit()


def test_frontend_defers_3d_refresh_within_budget_interval():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((1, 3), dtype=np.float32),
        orientations=np.eye(3, dtype=np.float32)[None, :, :],
        radii=np.ones(1, dtype=np.float32),
        lengths=np.ones(1, dtype=np.float32),
        entity_ids=("seg-a",),
        section_names=("sec-a",),
        xlocs=np.array([0.5], dtype=np.float32),
        labels=("sec-a@0.5",),
    )
    scene = AppSpec(
        fields={
            "voltage": Field(
                id="voltage",
                values=np.array([1.0], dtype=np.float32),
                dims=("segment",),
                coords={"segment": np.array(["seg-a"])},
            ),
        },
        geometries={geometry.id: geometry},
        views={
            "morphology": MorphologyViewSpec(
                id="morphology",
                geometry_id=geometry.id,
                color_field_id="voltage",
                sample_dim=None,
                max_refresh_hz=10.0,
            ),
        },
        layout=make_layout(
            "Deferred 3D view",
            panels=(view_3d_panel("morphology-panel", "morphology"),),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Deferred 3D view"))
    window.timer.stop()
    morphology_visual = view_3d_visual(window, "morphology", MORPHOLOGY_3D_VISUAL_KEY)
    morphology_visual.refresh = Mock()
    window.viewport.commit = Mock()
    window._view_3d_last_refresh_s["morphology"] = 10.0

    with patch.object(frontend_module.time, "monotonic", return_value=10.01):
        window._apply_refresh_targets({RefreshTarget.morphology("morphology")})

    morphology_visual.refresh.assert_not_called()
    assert window._dirty_view_3d_targets == {"morphology": {"morphology"}}

    with patch.object(frontend_module.time, "monotonic", return_value=10.11):
        window._flush_due_view_3d_refreshes()

    morphology_visual.refresh.assert_called_once()
    window.viewport.commit.assert_called_once()
    assert not window._dirty_view_3d_targets
    window.close()
    app.quit()


def test_frontend_can_force_3d_refresh_despite_budget():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((1, 3), dtype=np.float32),
        orientations=np.eye(3, dtype=np.float32)[None, :, :],
        radii=np.ones(1, dtype=np.float32),
        lengths=np.ones(1, dtype=np.float32),
        entity_ids=("seg-a",),
        section_names=("sec-a",),
        xlocs=np.array([0.5], dtype=np.float32),
        labels=("sec-a@0.5",),
    )
    scene = AppSpec(
        fields={
            "voltage": Field(
                id="voltage",
                values=np.array([1.0], dtype=np.float32),
                dims=("segment",),
                coords={"segment": np.array(["seg-a"])},
            ),
        },
        geometries={geometry.id: geometry},
        views={
            "morphology": MorphologyViewSpec(
                id="morphology",
                geometry_id=geometry.id,
                color_field_id="voltage",
                sample_dim=None,
                max_refresh_hz=10.0,
            ),
        },
        layout=make_layout(
            "Forced 3D view",
            panels=(view_3d_panel("morphology-panel", "morphology"),),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Forced 3D view"))
    window.timer.stop()
    morphology_visual = view_3d_visual(window, "morphology", MORPHOLOGY_3D_VISUAL_KEY)
    morphology_visual.refresh = Mock()
    window.viewport.commit = Mock()
    window._view_3d_last_refresh_s["morphology"] = 10.0

    with patch.object(frontend_module.time, "monotonic", return_value=10.01):
        window._apply_refresh_targets(
            {RefreshTarget.morphology("morphology")},
            force_view_3d=True,
        )

    morphology_visual.refresh.assert_called_once()
    window.viewport.commit.assert_called_once()
    assert not window._dirty_view_3d_targets
    window.close()
    app.quit()


def test_morphology_view_can_opt_out_of_frontend_refresh_throttle():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((1, 3), dtype=np.float32),
        orientations=np.eye(3, dtype=np.float32)[None, :, :],
        radii=np.ones(1, dtype=np.float32),
        lengths=np.ones(1, dtype=np.float32),
        entity_ids=("seg-a",),
        section_names=("sec-a",),
        xlocs=np.array([0.5], dtype=np.float32),
        labels=("sec-a@0.5",),
    )
    scene = AppSpec(
        fields={
            "voltage": Field(
                id="voltage",
                values=np.array([1.0], dtype=np.float32),
                dims=("segment",),
                coords={"segment": np.array(["seg-a"])},
            ),
        },
        geometries={geometry.id: geometry},
        views={
            "morphology": MorphologyViewSpec(
                id="morphology",
                geometry_id=geometry.id,
                color_field_id="voltage",
                sample_dim=None,
                max_refresh_hz=0.0,
            ),
        },
        layout=make_layout(
            "Unthrottled 3D view",
            panels=(view_3d_panel("morphology-panel", "morphology"),),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Unthrottled 3D view"))
    window.timer.stop()
    morphology_visual = view_3d_visual(window, "morphology", MORPHOLOGY_3D_VISUAL_KEY)
    morphology_visual.refresh = Mock()
    window.viewport.commit = Mock()
    window._view_3d_last_refresh_s["morphology"] = 10.0

    with patch.object(frontend_module.time, "monotonic", return_value=10.01):
        window._apply_refresh_targets({RefreshTarget.morphology("morphology")})

    morphology_visual.refresh.assert_called_once()
    window.viewport.commit.assert_called_once()
    assert not window._dirty_view_3d_targets
    window.close()
    app.quit()


def test_frontend_budgets_line_plot_refreshes_across_dirty_views():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scene = AppSpec(
        fields={
            "trace-a": Field(
                id="trace-a",
                values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
                dims=("time",),
                coords={"time": np.array([0.0, 1.0, 2.0], dtype=np.float32)},
            ),
            "trace-b": Field(
                id="trace-b",
                values=np.array([10.0, 20.0, 30.0], dtype=np.float32),
                dims=("time",),
                coords={"time": np.array([0.0, 1.0, 2.0], dtype=np.float32)},
            ),
        },
        geometries={},
        views={
            "trace-a": LinePlotViewSpec(id="trace-a", field_id="trace-a", x_dim="time", max_refresh_hz=0.0),
            "trace-b": LinePlotViewSpec(id="trace-b", field_id="trace-b", x_dim="time", max_refresh_hz=0.0),
        },
        layout=make_layout(
            "Budgeted line plots",
            panels=(
                line_plot_panel_spec("trace-a-panel", "trace-a"),
                line_plot_panel_spec("trace-b-panel", "trace-b"),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Budgeted line plots"))
    window.timer.stop()
    window.line_plot_host_panels["trace-a-panel"].refresh = Mock()
    window.line_plot_host_panels["trace-b-panel"].refresh = Mock()
    window._dirty_line_plot_views.update({"trace-a", "trace-b"})
    window._line_plot_last_refresh_s["trace-a"] = 1.0
    window._line_plot_last_refresh_s["trace-b"] = 2.0

    window._flush_due_line_plot_refreshes(now=3.0)

    window.line_plot_host_panels["trace-a-panel"].refresh.assert_called_once()
    window.line_plot_host_panels["trace-b-panel"].refresh.assert_not_called()
    assert window._dirty_line_plot_views == {"trace-b"}

    window._flush_due_line_plot_refreshes(now=3.0)

    window.line_plot_host_panels["trace-b-panel"].refresh.assert_called_once()
    assert not window._dirty_line_plot_views
    window.close()
    app.quit()


def test_line_plot_panel_uses_colors_sequence_for_multi_series():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="cascade",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("series", "time"),
        coords={
            "series": np.array(["ligand", "receptor"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="cascade-plot",
        field_id=field.id,
        x_dim="time",
        series_dim="series",
        colors=("#ff0000", "#0000ff"),
    )

    panel.refresh(view, field, {})

    ligand_pen = panel._series_items["ligand"].opts["pen"]
    receptor_pen = panel._series_items["receptor"].opts["pen"]
    assert ligand_pen.color().name() == "#ff0000"
    assert receptor_pen.color().name() == "#0000ff"
    app.quit()


def test_line_plot_panel_applies_rolling_window_and_y_range():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="trace",
        values=np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)},
    )
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id=field.id,
        x_dim="time",
        rolling_window=1.5,
        y_min=0.0,
        y_max=5.0,
    )

    panel.refresh(view, field, {})
    view_range = panel.plotItem.getViewBox().viewRange()

    assert np.allclose(view_range[0], [1.5, 3.0])
    assert np.allclose(view_range[1], [0.0, 5.0])
    app.quit()


def test_line_plot_panel_clamps_rolling_window_to_available_history():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="trace",
        values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([0.0, 50.0, 100.0], dtype=np.float32)},
    )
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id=field.id,
        x_dim="time",
        rolling_window=120.0,
    )

    panel.refresh(view, field, {})
    view_range = panel.plotItem.getViewBox().viewRange()

    assert np.allclose(view_range[0], [0.0, 100.0])
    app.quit()


def test_line_plot_panel_resets_single_sample_rolling_window_without_negative_backfill():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id="trace",
        x_dim="time",
        rolling_window=30.0,
    )
    field_before = Field(
        id="trace",
        values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([90.0, 100.0, 120.0], dtype=np.float32)},
    )
    field_after = Field(
        id="trace",
        values=np.array([1.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([0.0], dtype=np.float32)},
    )

    panel.refresh(view, field_before, {})
    panel.refresh(view, field_after, {})
    view_range = panel.plotItem.getViewBox().viewRange()

    assert np.allclose(view_range[0], [0.0, 30.0])
    app.quit()


def test_line_plot_panel_can_trim_data_to_rolling_window():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="trace",
        values=np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)},
    )
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id=field.id,
        x_dim="time",
        rolling_window=1.5,
        trim_to_rolling_window=True,
    )

    panel.refresh(view, field, {})
    x_data, y_data = panel._plot_item.getData()

    assert np.allclose(x_data, np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(y_data, np.array([2.0, 3.0, 4.0], dtype=np.float32))
    app.quit()


def test_multi_series_line_plot_can_trim_data_to_rolling_window():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="cascade",
        values=np.array([[1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]], dtype=np.float32),
        dims=("series", "time"),
        coords={
            "series": np.array(["ligand", "receptor"]),
            "time": np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="cascade-plot",
        field_id=field.id,
        x_dim="time",
        series_dim="series",
        rolling_window=1.5,
        trim_to_rolling_window=True,
    )

    panel.refresh(view, field, {})
    ligand_x, ligand_y = panel._series_items["ligand"].getData()
    receptor_x, receptor_y = panel._series_items["receptor"].getData()

    assert np.allclose(ligand_x, np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(ligand_y, np.array([2.0, 3.0, 4.0], dtype=np.float32))
    assert np.allclose(receptor_x, np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(receptor_y, np.array([20.0, 30.0, 40.0], dtype=np.float32))
    app.quit()


def test_line_plot_trim_keeps_last_sample_before_window_boundary():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    x = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
    y = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id="trace",
        x_dim="time",
        rolling_window=1.5,
        trim_to_rolling_window=True,
    )

    trimmed_x, trimmed_y = panel._trim_line_data(view, x, y)

    assert np.allclose(trimmed_x, np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert np.allclose(trimmed_y, np.array([2.0, 3.0, 4.0], dtype=np.float32))
    app.quit()


def test_line_plot_trim_drops_nonfinite_history_samples():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    x = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
    y = np.array([np.nan, np.nan, 3.0, 4.0], dtype=np.float32)
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id="trace",
        x_dim="time",
        rolling_window=10.0,
        trim_to_rolling_window=True,
    )

    trimmed_x, trimmed_y = panel._trim_line_data(view, x, y)

    assert np.allclose(trimmed_x, np.array([2.0, 3.0], dtype=np.float32))
    assert np.allclose(trimmed_y, np.array([3.0, 4.0], dtype=np.float32))
    app.quit()


def test_line_plot_panel_supports_multi_selected_morphology_traces():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="voltage",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="trace",
        field_id=field.id,
        x_dim="time",
        series_dim="segment",
        selectors={"segment": StateBinding("selected_trace_entity_ids")},
        title="Selected voltages",
    )

    panel.refresh(view, field, {"selected_trace_entity_ids": ["seg-b", "seg-a"]})

    assert set(panel._series_items.keys()) == {"seg-a", "seg-b"}
    seg_b_x, seg_b_y = panel._series_items["seg-b"].getData()
    assert np.allclose(seg_b_x, np.array([0.0, 1.0, 2.0], dtype=np.float32))
    assert np.allclose(seg_b_y, np.array([10.0, 20.0, 30.0], dtype=np.float32))
    app.quit()


def test_line_plot_panel_drops_nonfinite_prefix_for_sparse_selected_trace_history():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="segment_history",
        values=np.array([[1.0, 2.0, 3.0, 4.0], [np.nan, np.nan, 30.0, 40.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="trace",
        field_id=field.id,
        x_dim="time",
        series_dim="segment",
        selectors={"segment": StateBinding("selected_trace_entity_ids")},
        trim_to_rolling_window=True,
        rolling_window=10.0,
    )

    panel.refresh(view, field, {"selected_trace_entity_ids": ["seg-a", "seg-b"]})

    seg_b_x, seg_b_y = panel._series_items["seg-b"].getData()
    assert np.allclose(seg_b_x, np.array([2.0, 3.0], dtype=np.float32))
    assert np.allclose(seg_b_y, np.array([30.0, 40.0], dtype=np.float32))
    app.quit()


def test_multi_series_rolling_window_uses_visible_finite_history_for_x_range():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="segment_history",
        values=np.array([[np.nan, np.nan, 30.0, 40.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-b"]),
            "time": np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="trace",
        field_id=field.id,
        x_dim="time",
        series_dim="segment",
        selectors={"segment": StateBinding("selected_trace_entity_ids")},
        rolling_window=10.0,
    )

    panel.refresh(view, field, {"selected_trace_entity_ids": ["seg-b"]})
    view_range = panel.plotItem.getViewBox().viewRange()

    assert np.allclose(view_range[0], [2.0, 3.0])
    app.quit()


def test_line_plot_panel_ignores_missing_selected_trace_labels_for_sparse_history():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="segment_history",
        values=np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="trace",
        field_id=field.id,
        x_dim="time",
        series_dim="segment",
        selectors={"segment": StateBinding("selected_trace_entity_ids")},
        title="Selected voltages",
    )

    panel.refresh(view, field, {"selected_trace_entity_ids": ["seg-a", "seg-b"]})

    assert set(panel._series_items.keys()) == {"seg-a"}
    app.quit()


def test_line_plot_panel_applies_explicit_x_tick_spacing():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="trace",
        values=np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)},
    )
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id=field.id,
        x_dim="time",
        x_major_tick_spacing=5.0,
        x_minor_tick_spacing=1.0,
        rolling_window=30.0,
    )
    panel.refresh(view, field, {})
    ticks = panel.plotItem.getAxis("bottom")._tickLevels
    assert ticks is not None
    major = ticks[0]
    minor = ticks[1]
    assert [value for value, _ in major] == [0.0]
    assert [label for _, label in major] == ["0"]
    assert [value for value, _ in minor] == [1.0, 2.0, 3.0]
    assert all(label == "" for _, label in minor)
    app.quit()


def test_line_plot_panel_updates_manual_ticks_when_window_crosses_minor_spacing():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    view = LinePlotViewSpec(
        id="trace-plot",
        field_id="trace",
        x_dim="time",
        x_major_tick_spacing=5.0,
        x_minor_tick_spacing=1.0,
        rolling_window=2.9,
    )
    field_before = Field(
        id="trace",
        values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([0.1, 1.1, 3.0], dtype=np.float32)},
    )
    field_after = Field(
        id="trace",
        values=np.array([1.0, 2.0, 3.0], dtype=np.float32),
        dims=("time",),
        coords={"time": np.array([1.1, 2.1, 4.0], dtype=np.float32)},
    )

    panel.refresh(view, field_before, {})
    panel.refresh(view, field_after, {})
    ticks = panel.plotItem.getAxis("bottom")._tickLevels

    assert ticks is not None
    minor = ticks[1]
    assert [value for value, _ in minor] == [2.0, 3.0, 4.0]
    app.quit()


def test_frontend_hides_viewport_when_scene_has_no_3d_view():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="cascade",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("series", "time"),
        coords={
            "series": np.array(["ligand", "receptor"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={},
        views={
            "cascade-plot": LinePlotViewSpec(
                id="cascade-plot",
                field_id=field.id,
                x_dim="time",
                series_dim="series",
            )
        },
        layout=make_layout(
            "Cascade",
            panels=(line_plot_panel_spec("cascade-plot-panel", "cascade-plot"),),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Cascade"))
    window.timer.stop()

    assert window.viewport is None
    assert not window.controls_host_panels
    assert isinstance(window.centralWidget(), QtWidgets.QStackedWidget)
    assert window._stack.currentWidget() is window._layout_splitter
    assert window._layout_splitter.orientation() == QtCore.Qt.Orientation.Vertical
    assert "cascade-plot-panel" in window.line_plot_panels

    window.close()
    app.quit()


def test_frontend_uses_splitters_for_draggable_panel_resize():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = VispyFrontendWindow(build_surface_cross_section_app())
    window.timer.stop()

    assert isinstance(window.centralWidget(), QtWidgets.QStackedWidget)
    assert window._stack.currentWidget() is window._layout_splitter
    assert window._layout_splitter.orientation() == QtCore.Qt.Orientation.Vertical
    row = window._layout_splitter.widget(0)
    assert isinstance(row, QtWidgets.QSplitter)
    assert row.orientation() == QtCore.Qt.Orientation.Horizontal
    assert row.widget(0) is window.view_hosts["surface-host"]
    assert isinstance(row.widget(1), LinePlotHostPanel)
    assert row.widget(1).line_plot_panel is window.line_plot_panels["surface-line-panel"]
    assert window._layout_splitter.widget(1) is resolved_controls_host(window)
    assert resolved_controls_host(window).controls_panel is resolved_controls_panel(window)
    assert not hasattr(window, "controls")
    assert not hasattr(window, "control_host")
    assert not hasattr(window, "line_plot")
    assert not hasattr(window, "line_plots")
    assert not hasattr(window, "line_plot_for")
    assert not hasattr(resolved_controls_host(window), "controls")
    assert not window._layout_splitter.opaqueResize()
    assert not row.opaqueResize()

    window.close()
    app.quit()


def test_frontend_supports_multiple_3d_viewports():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    morph_geometry = MorphologyGeometry(
        id="morphology-geometry",
        positions=np.zeros((1, 3), dtype=np.float32),
        orientations=np.eye(3, dtype=np.float32)[None, :, :],
        radii=np.ones(1, dtype=np.float32),
        lengths=np.ones(1, dtype=np.float32),
        entity_ids=("seg-a",),
        section_names=("sec-a",),
        xlocs=np.array([0.5], dtype=np.float32),
        labels=("sec-a@0.5",),
    )
    morph_field = Field(
        id="voltage",
        values=np.array([1.0], dtype=np.float32),
        dims=("segment",),
        coords={"segment": np.array(["seg-a"])},
    )
    surface_field, surface_geometry = grid_field(
        field_id="surface",
        values=np.ones((4, 4), dtype=np.float32),
        x_coords=np.linspace(-1.0, 1.0, 4, dtype=np.float32),
        y_coords=np.linspace(-1.0, 1.0, 4, dtype=np.float32),
    )
    scene = AppSpec(
        fields={morph_field.id: morph_field, surface_field.id: surface_field},
        geometries={morph_geometry.id: morph_geometry, surface_geometry.id: surface_geometry},
        views={
            "morphology": MorphologyViewSpec(id="morphology", geometry_id=morph_geometry.id, color_field_id=morph_field.id),
            "surface-view": SurfaceViewSpec(id="surface-view", field_id=surface_field.id, geometry_id=surface_geometry.id),
        },
        layout=make_layout(
            "Multi 3D",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                view_3d_panel("surface-panel", "surface-view"),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Multi 3D"))
    window.timer.stop()

    assert set(window.viewports.keys()) == {"morphology", "surface-view"}
    assert window.viewport_for("morphology") is not None
    assert window.viewport_for("surface-view") is not None
    row = window._layout_splitter.widget(0)
    assert isinstance(row, QtWidgets.QSplitter)
    assert row.count() == 2
    assert not window.controls_host_panels

    window.close()
    app.quit()


def test_layout_spec_derives_default_panels_with_standardized_ids():
    scene = AppSpec(
        fields={},
        geometries={},
        views={
            "morphology": MorphologyViewSpec(id="morphology", geometry_id="morphology-geometry"),
            "surface": SurfaceViewSpec(id="surface", field_id="surface-field", geometry_id="surface-geometry"),
            "trace": LinePlotViewSpec(id="trace", field_id="trace-field", x_dim="time"),
            "states": StateGraphViewSpec(id="states"),
        },
        actions={"reset": ActionSpec(id="reset", label="Reset")},
        layout=LayoutSpec(title="Derived panels"),
    )

    assert tuple(panel.id for panel in scene.active_layout().panels) == (
        "morphology-panel",
        "surface-panel",
        "trace-panel",
        "states-panel",
        "controls-panel",
    )
    assert scene.active_layout().panel_grid == ()


def test_frontend_builds_explicit_independent_3d_hosts():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    geometry = MorphologyGeometry(
        id="morphology-geometry",
        positions=np.zeros((1, 3), dtype=np.float32),
        orientations=np.eye(3, dtype=np.float32)[None, :, :],
        radii=np.ones(1, dtype=np.float32),
        lengths=np.ones(1, dtype=np.float32),
        entity_ids=("seg-a",),
        section_names=("sec-a",),
        xlocs=np.array([0.5], dtype=np.float32),
        labels=("sec-a@0.5",),
    )
    field = Field(
        id="display",
        values=np.array([1.0], dtype=np.float32),
        dims=("segment",),
        coords={"segment": np.array(["seg-a"])},
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={"morphology": MorphologyViewSpec(id="morphology", geometry_id=geometry.id, color_field_id=field.id)},
        layout=make_layout(
            "Hosted",
            panels=(view_3d_panel("main-host", "morphology", title="Primary 3D"),),
        ),
    )

    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Hosted"))
    window.timer.stop()

    assert set(window.view_hosts.keys()) == {"main-host"}
    assert window._view_to_panel_id["morphology"] == "main-host"
    assert window.view_hosts["main-host"].title() == "Primary 3D"
    assert window.viewport_for("morphology") is window.view_hosts["main-host"].viewport

    window.close()
    app.quit()


def test_controls_panel_renders_and_dispatches_scene_actions():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [2.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={
            "morphology": MorphologyViewSpec(id="morphology", geometry_id=geometry.id)
        },
        actions={
            "mark_selected": ActionSpec(
                id="mark_selected",
                label="Mark selected",
                payload={"entity_id": StateBinding("selected_entity_id")},
            )
        },
        layout=make_layout(
            "Action test",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                controls_panel_spec(action_ids=("mark_selected",)),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Action test"))
    window.timer.stop()
    window.transport = Mock()
    window.state["selected_entity_id"] = "seg-a"

    action_button = resolved_controls_panel(window).widgets["mark_selected"]
    action_button.click()

    window.transport.send.assert_called_once()
    command = window.transport.send.call_args[0][0].payload
    assert command.action_id == "mark_selected"
    assert command.payload["entity_id"] == "seg-a"

    window.close()
    app.quit()


def test_controls_host_title_reflects_controls_and_actions_presence():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = VispyFrontendWindow(build_surface_cross_section_app())
    window.timer.stop()

    assert resolved_controls_host(window).title() == "Controls"

    actions_only_scene = AppSpec(
        fields={},
        geometries={},
        views={},
        actions={"reset": ActionSpec(id="reset", label="Reset")},
        layout=make_layout("Actions only", panels=(controls_panel_spec(),)),
    )
    window._set_app_spec(actions_only_scene)
    assert resolved_controls_host(window).title() == "Actions"

    controls_and_actions_scene = AppSpec(
        fields={},
        geometries={},
        views={},
        controls={"gain": float_control("gain", "Gain", 1.0)},
        actions={"reset": ActionSpec(id="reset", label="Reset")},
        layout=make_layout(
            "Controls and actions",
            panels=(controls_panel_spec(control_ids=("gain",), action_ids=("reset",)),),
        ),
    )
    window._set_app_spec(controls_and_actions_scene)
    assert resolved_controls_host(window).title() == "Controls & Actions"

    window.close()
    app.quit()


def test_controls_host_uses_scroll_area_for_overflowing_controls():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = VispyFrontendWindow(build_surface_cross_section_app())
    window.timer.stop()

    host = resolved_controls_host(window)
    panel = resolved_controls_panel(window)
    assert isinstance(host.scroll_area, QtWidgets.QScrollArea)
    assert host.scroll_area.widgetResizable()
    assert host.scroll_area.widget() is panel
    assert host.scroll_area.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert host.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Policy.Ignored

    window.close()
    app.quit()


def test_controls_panel_switches_to_two_columns_when_wide():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = ControlsPanel(lambda *_args: None)
    controls = [
        float_control(f"gain_{index}", f"Gain {index}", 1.0, 0.0, 2.0)
        for index in range(8)
    ]

    panel.resize(1100, 480)
    panel.show()
    app.processEvents()
    panel.set_controls(controls, [], {})
    app.processEvents()
    assert panel._column_count == 2

    panel.resize(700, 480)
    app.processEvents()
    assert panel._column_count == 1

    panel.close()
    app.quit()


def test_action_shortcut_dispatches_invoke_action():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    scene = AppSpec(
        fields={},
        geometries={},
        views={},
        actions={
            "toggle": ActionSpec(
                id="toggle",
                label="Toggle",
                payload={"selected": StateBinding("selected_entity_id")},
                shortcuts=("I",),
            )
        },
        layout=make_layout("Shortcut test", panels=(controls_panel_spec(action_ids=("toggle",)),)),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Shortcut test"))
    window.timer.stop()
    window.transport = Mock()
    window.state["selected_entity_id"] = "seg-a"

    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_I, QtCore.Qt.KeyboardModifier.NoModifier, "i")
    window.keyPressEvent(event)

    window.transport.send.assert_called_once()
    command = window.transport.send.call_args[0][0].payload
    assert command.action_id == "toggle"
    assert command.payload["selected"] == "seg-a"

    window.close()
    app.quit()


def test_selection_mode_action_arms_on_shortcut_and_fires_on_click():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [2.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={"morphology": MorphologyViewSpec(id="morphology", geometry_id=geometry.id)},
        actions={
            "arm_add": ActionSpec(
                id="arm_add",
                label="Arm add",
                shortcuts=("1",),
                selection_mode=True,
            )
        },
        layout=make_layout(
            "Selection action test",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                controls_panel_spec(action_ids=("arm_add",)),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Selection action test"))
    window.timer.stop()
    window.transport = Mock()

    arm_event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_1, QtCore.Qt.KeyboardModifier.NoModifier, "1")
    window.keyPressEvent(arm_event)
    assert window.transport.send.call_count == 0

    window._on_entity_selected("seg-b")

    window.transport.send.assert_called_once()
    command = window.transport.send.call_args[0][0].payload
    assert command.action_id == "arm_add"
    assert command.payload["entity_id"] == "seg-b"

    window.close()
    app.quit()


class DummyInteractionTarget:
    def __init__(self):
        self.mode_enabled = False
        self.clicked_entities = []

    def on_action(self, action_id, payload, context):
        del payload
        if action_id == "toggle_mode":
            self.mode_enabled = not self.mode_enabled
            context.show_status("Mode enabled" if self.mode_enabled else "Mode disabled")
            return True
        if action_id == "clear_targets":
            self.clicked_entities.clear()
            return False
        return False

    def on_entity_clicked(self, entity_id, context):
        if not self.mode_enabled:
            return False
        self.clicked_entities.append(entity_id)
        context.invoke_action("register_entity", {"entity_id": entity_id})
        return True


def test_interaction_callbacks_can_handle_mode_and_entity_click_without_selection_mode():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [2.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={"morphology": MorphologyViewSpec(id="morphology", geometry_id=geometry.id)},
        actions={
            "toggle_mode": ActionSpec(id="toggle_mode", label="Toggle mode", shortcuts=("1",)),
            "register_entity": ActionSpec(id="register_entity", label="Register entity"),
            "clear_targets": ActionSpec(id="clear_targets", label="Clear targets"),
        },
        layout=make_layout(
            "Callback interaction test",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                controls_panel_spec(action_ids=("toggle_mode", "clear_targets")),
            ),
        ),
    )
    interaction_target = DummyInteractionTarget()
    window = VispyFrontendWindow(RunSpec(app_spec=scene, interaction_target=interaction_target, title="Callback interaction test"))
    window.timer.stop()
    window.transport = Mock()

    toggle_event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_1, QtCore.Qt.KeyboardModifier.NoModifier, "1")
    window.keyPressEvent(toggle_event)
    assert interaction_target.mode_enabled is True
    assert window.transport.send.call_count == 0

    window._on_entity_selected("seg-b")

    window.transport.send.assert_called_once()
    command = window.transport.send.call_args[0][0].payload
    assert command.action_id == "register_entity"
    assert command.payload["entity_id"] == "seg-b"
    assert interaction_target.clicked_entities == ["seg-b"]

    window.close()
    app.quit()


def test_frontend_interaction_context_resolves_entity_info_from_scene():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [2.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={"morphology": MorphologyViewSpec(id="morphology", geometry_id=geometry.id)},
        layout=make_layout("Entity info test", panels=(view_3d_panel("morphology-panel", "morphology"),)),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Entity info test"))
    window.timer.stop()

    info = window._interaction_context().entity_info("seg-b")

    assert info is not None
    assert info["entity_id"] == "seg-b"
    assert info["section_name"] == "sec-b"
    assert info["label"] == "sec-b@0.9"

    window.close()
    app.quit()


def test_frontend_reset_action_sends_reset_command():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [2.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={"morphology": MorphologyViewSpec(id="morphology", geometry_id=geometry.id)},
        actions={"reset": ActionSpec(id="reset", label="Reset")},
        layout=make_layout(
            "Reset button test",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                controls_panel_spec(action_ids=("reset",)),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Reset button test"))
    window.timer.stop()
    window.transport = Mock()

    window._on_action_invoked(scene.interactions.actions["reset"], {})

    window.transport.send.assert_called_once()
    command = window.transport.send.call_args[0][0].payload
    assert isinstance(command, Reset)

    window.close()
    app.quit()


class DummyNeuronBackend(NeuronBackend):
    def __init__(self):
        super().__init__(title="Dummy neuron app")

    def build_sections(self):
        return []

    def control_specs(self):
        return {"gain": float_control("gain", "Gain", 1.0)}

    def action_specs(self):
        return {"toggle_mode": ActionSpec("toggle_mode", "Toggle mode")}

    def control_order(self):
        return ("gain",)

    def action_order(self):
        return ("toggle_mode",)

    def trace_view_updates(self):
        return {"rolling_window": 25.0, "trim_to_rolling_window": True}


def test_neuron_session_build_app_spec_applies_orders_and_trace_updates():
    backend = DummyNeuronBackend()
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((1, 3), dtype=np.float32),
        orientations=np.eye(3, dtype=np.float32)[None, :, :],
        radii=np.ones(1, dtype=np.float32),
        lengths=np.ones(1, dtype=np.float32),
        entity_ids=("seg-a",),
        section_names=("sec-a",),
        xlocs=np.array([0.5], dtype=np.float32),
        labels=("sec-a@0.5",),
    )

    scene = backend.build_app_spec(
        geometry=geometry,
        display_values=np.array([1.0], dtype=np.float32),
        time_value=0.0,
    )

    controls_panel = scene.active_layout().panel("controls-panel")
    assert controls_panel is not None
    assert controls_panel.control_ids == ("gain",)
    assert controls_panel.action_ids == ("toggle_mode",)
    trace_view = scene.view_catalog.views["trace"]
    assert trace_view.rolling_window == 25.0
    assert trace_view.trim_to_rolling_window is True


def test_neuron_session_defaults_to_batched_display_updates():
    backend = DummyNeuronBackend()

    assert backend.sim_ms_per_frame() == pytest.approx(0.1)


class WindowBudgetNeuronBackend(NeuronBackend):
    def __init__(self):
        super().__init__(dt=0.1, max_samples=1000, title="Window budget")

    def build_sections(self):
        return []

    def trace_view_updates(self):
        return {"rolling_window": 120.0}


def test_neuron_session_expands_history_budget_to_cover_trace_window():
    backend = WindowBudgetNeuronBackend()
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((1, 3), dtype=np.float32),
        orientations=np.eye(3, dtype=np.float32)[None, :, :],
        radii=np.ones(1, dtype=np.float32),
        lengths=np.ones(1, dtype=np.float32),
        entity_ids=("seg-a",),
        section_names=("sec-a",),
        xlocs=np.array([0.5], dtype=np.float32),
        labels=("sec-a@0.5",),
    )
    scene = backend.build_app_spec(
        geometry=geometry,
        display_values=np.array([1.0], dtype=np.float32),
        time_value=0.0,
    )

    assert backend._resolved_field_max_samples(scene, field_id=NeuronAppSpecBuilder.HISTORY_FIELD_ID, append_dim="time") == 1201


def test_frontend_applies_field_append_updates_incrementally():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [10.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={
            "morphology": MorphologyViewSpec(
                id="morphology",
                geometry_id=geometry.id,
                color_field_id=field.id,
                entity_dim="segment",
                sample_dim="time",
            ),
            "trace": LinePlotViewSpec(
                id="trace",
                field_id=field.id,
                x_dim="time",
                selectors={"segment": StateBinding("selected_entity_id")},
            ),
        },
        layout=make_layout(
            "Append test",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                line_plot_panel_spec("trace-panel", "trace"),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Append test"))
    window.timer.stop()
    window.state["selected_entity_id"] = "seg-a"
    window.transport = Mock()
    window.transport.poll.return_value = update_messages(
        FieldAppend(
            field_id="voltage",
            append_dim="time",
            values=np.array([[2.0, 3.0], [20.0, 30.0]], dtype=np.float32),
            coord_values=np.array([1.0, 2.0], dtype=np.float32),
            max_length=2,
        )
    )

    window._poll_transport()

    updated = window.app_spec.data.fields["voltage"]
    assert updated.coord("time").tolist() == [1.0, 2.0]
    assert np.allclose(updated.values, np.array([[2.0, 3.0], [20.0, 30.0]], dtype=np.float32))
    window._flush_due_line_plot_refreshes(force=True)
    x_data, y_data = window.line_plot_panel("trace")._plot_item.getData()
    assert np.allclose(x_data, np.array([1.0, 2.0], dtype=np.float32))
    assert np.allclose(y_data, np.array([2.0, 3.0], dtype=np.float32))

    window.close()
    app.quit()


def test_frontend_batches_multiple_field_appends_into_one_refresh_pass():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [10.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={
            "morphology": MorphologyViewSpec(
                id="morphology",
                geometry_id=geometry.id,
                color_field_id=field.id,
                entity_dim="segment",
                sample_dim="time",
            ),
            "trace": LinePlotViewSpec(
                id="trace",
                field_id=field.id,
                x_dim="time",
                selectors={"segment": StateBinding("selected_entity_id")},
            ),
        },
        layout=make_layout(
            "Batch append test",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                line_plot_panel_spec("trace-panel", "trace"),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Batch append test"))
    window.timer.stop()
    window.transport = Mock()
    window._flush_due_line_plot_refreshes = Mock(return_value=(1, 0))
    window._flush_due_view_3d_refreshes = Mock(return_value=(1, 0))
    window.transport.poll.return_value = update_messages(
        FieldAppend(
            field_id="voltage",
            append_dim="time",
            values=np.array([[2.0], [20.0]], dtype=np.float32),
            coord_values=np.array([1.0], dtype=np.float32),
            max_length=3,
        ),
        FieldAppend(
            field_id="voltage",
            append_dim="time",
            values=np.array([[3.0], [30.0]], dtype=np.float32),
            coord_values=np.array([2.0], dtype=np.float32),
            max_length=3,
        ),
    )

    with patch.object(Field, "append", autospec=True, side_effect=Field.append) as append_spy:
        window._poll_transport()

    updated = window.app_spec.data.fields["voltage"]
    assert updated.coord("time").tolist() == [0.0, 1.0, 2.0]
    assert np.allclose(updated.values, np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32))
    append_spy.assert_called_once()
    window._flush_due_line_plot_refreshes.assert_called_once()
    window._flush_due_view_3d_refreshes.assert_called_once()

    window.close()
    app.quit()


def test_frontend_flushes_buffered_field_appends_before_field_replace():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    field = Field(
        id="voltage",
        values=np.array([[1.0], [10.0]], dtype=np.float32),
        dims=("segment", "time"),
        coords={
            "segment": np.array(["seg-a", "seg-b"]),
            "time": np.array([0.0], dtype=np.float32),
        },
    )
    geometry = MorphologyGeometry(
        id="morphology",
        positions=np.zeros((2, 3), dtype=np.float32),
        orientations=np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 2, axis=0),
        radii=np.ones(2, dtype=np.float32),
        lengths=np.ones(2, dtype=np.float32),
        entity_ids=("seg-a", "seg-b"),
        section_names=("sec-a", "sec-b"),
        xlocs=np.array([0.1, 0.9], dtype=np.float32),
        labels=("sec-a@0.1", "sec-b@0.9"),
    )
    scene = AppSpec(
        fields={field.id: field},
        geometries={geometry.id: geometry},
        views={
            "morphology": MorphologyViewSpec(
                id="morphology",
                geometry_id=geometry.id,
                color_field_id=field.id,
                entity_dim="segment",
                sample_dim="time",
            ),
            "trace": LinePlotViewSpec(
                id="trace",
                field_id=field.id,
                x_dim="time",
                selectors={"segment": StateBinding("selected_entity_id")},
            ),
        },
        layout=make_layout(
            "Append replace order test",
            panels=(
                view_3d_panel("morphology-panel", "morphology"),
                line_plot_panel_spec("trace-panel", "trace"),
            ),
        ),
    )
    window = VispyFrontendWindow(RunSpec(app_spec=scene, title="Append replace order test"))
    window.timer.stop()
    window.state["selected_entity_id"] = "seg-a"
    window.transport = Mock()
    window.transport.poll.return_value = update_messages(
        FieldAppend(
            field_id="voltage",
            append_dim="time",
            values=np.array([[2.0], [20.0]], dtype=np.float32),
            coord_values=np.array([1.0], dtype=np.float32),
            max_length=4,
        ),
        FieldReplace(
            field_id="voltage",
            values=np.array([[100.0], [200.0]], dtype=np.float32),
            coords={
                "segment": np.array(["seg-a", "seg-b"]),
                "time": np.array([5.0], dtype=np.float32),
            },
        ),
        FieldAppend(
            field_id="voltage",
            append_dim="time",
            values=np.array([[300.0], [400.0]], dtype=np.float32),
            coord_values=np.array([6.0], dtype=np.float32),
            max_length=4,
        ),
    )

    window._poll_transport()

    updated = window.app_spec.data.fields["voltage"]
    assert updated.coord("time").tolist() == [5.0, 6.0]
    assert np.allclose(updated.values, np.array([[100.0, 300.0], [200.0, 400.0]], dtype=np.float32))

    window.close()
    app.quit()


def test_multi_series_refresh_keeps_existing_legend_when_series_are_stable():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = LinePlotPanel()
    field = Field(
        id="cascade",
        values=np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]], dtype=np.float32),
        dims=("series", "time"),
        coords={
            "series": np.array(["ligand", "receptor"]),
            "time": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    view = LinePlotViewSpec(
        id="cascade-plot",
        field_id=field.id,
        x_dim="time",
        series_dim="series",
        show_legend=True,
    )

    panel.refresh(view, field, {})
    legend = panel.plotItem.legend
    assert legend is not None
    original_clear = legend.clear
    original_add = legend.addItem
    legend.clear = Mock(wraps=original_clear)
    legend.addItem = Mock(wraps=original_add)

    panel.refresh(view, field.with_values(field.values + 1.0), {})

    legend.clear.assert_not_called()
    legend.addItem.assert_not_called()
    app.quit()


def test_morphology_renderer_decode_pick_index_reads_exact_pick_pixel():
    renderer = MorphologyRenderer.__new__(MorphologyRenderer)
    img = np.zeros((1, 1, 3), dtype=np.uint8)
    cid = 2
    img[0, 0, 0] = cid & 0xFF
    img[0, 0, 1] = (cid >> 8) & 0xFF
    img[0, 0, 2] = (cid >> 16) & 0xFF

    idx = renderer._decode_pick_index(img)

    assert idx == 1
