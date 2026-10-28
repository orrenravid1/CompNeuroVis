from __future__ import annotations

import importlib
import multiprocessing
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

import compneurovis as cnv
import compneurovis.inline as inline
from _click_fixtures import clicked
from compneurovis.core.messages import (
    PointerInteractionEvent,
    FieldReplace,
    ValueChange,
    command_message,
)
from compneurovis._source_runtime import build_multi_source_run_plan


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "extensions" / "cnv_pointcloud_demo"
LOCAL_FIXTURE = ROOT / "examples" / "extensions" / "local_gauge"
PAINT_FIXTURE = (
    ROOT / "examples" / "extensions" / "morphology_tools_demo" / "painting"
)


def _lower(source):
    source._panel_grid = inline._current_authoring_app()._panel_grid
    backend = source._make_backend()
    return source._build_app_spec_for_backend(backend)


def _inspect_pipe_payload(connection):
    app = connection.recv()
    geometry = next(iter(app.data.geometries.values()))
    operator = next(iter(app.view_catalog.operators.values()))
    contribution = next(iter(app.view_catalog.contributions.values()))
    scatter = next(
        view for view in app.view_catalog.views.values() if view.kind == "scatter_2d"
    )
    connection.send(
        (
            isinstance(geometry, cnv.GeometrySpec),
            geometry.kind,
            isinstance(operator, cnv.OperatorSpec),
            operator.kind,
            operator.geometries["points"] == geometry.id,
            scatter.inputs["data"] == operator.id,
            isinstance(contribution, cnv.VisualContributionSpec),
            contribution.inputs["slice"] == operator.id,
            "pointcloud_vispy" in sys.modules,
        )
    )
    connection.close()


@dataclass(frozen=True, slots=True)
class _MorphologyToolRef:
    weights: object
    markers: object


class _MorphologyTool(cnv.Widget[_MorphologyToolRef]):
    """External-style tool composed entirely from public authoring primitives."""

    def __init__(self, morphology, *, mode, weight, entity_ids):
        self.morphology = morphology
        self.mode = mode
        self.weight = weight
        self.entity_ids = tuple(entity_ids)

    def declare(self, context):
        weights_state = np.zeros(len(self.entity_ids), dtype=np.float32)
        marker_rows: list[list[float]] = []
        weights = context.data(
            "paint weights",
            values=weights_state,
            labels=self.entity_ids,
        )
        marker_columns = ("x", "y", "z", "r", "g", "b", "a", "size")
        markers = context.snapshot(
            "markers",
            dims=("marker", "attribute"),
            coords={"marker": (), "attribute": marker_columns},
            values=np.empty((0, len(marker_columns)), dtype=np.float32),
        )
        context.visual_contribution(
            "test_weight_layer",
            "weights",
            target=self.morphology,
            capability="scene3d.layers/v1",
            inputs={"values": weights},
            geometries={"morphology": self.morphology.geometry},
        )
        context.visual_contribution(
            "test_marker_layer",
            "markers",
            target=self.morphology,
            capability="scene3d.layers/v1",
            inputs={"markers": markers},
            geometries={"morphology": self.morphology.geometry},
        )

        def handle_click(ctx, entity_id):
            mode = ctx.get_value(self.mode)
            info = ctx.entity_info(entity_id)
            assert info is not None
            if mode == "paint":
                weights_state[int(info["index"])] = float(
                    ctx.get_value(self.weight)
                )
                ctx.set_data(weights, weights_state.copy())
                return True
            if mode == "mark":
                position = tuple(float(value) for value in info["position"])
                marker_rows.append([*position, 1.0, 0.25, 0.1, 1.0, 4.0])
                ctx.set_data(
                    markers,
                    np.asarray(marker_rows, dtype=np.float32),
                    coords={
                        "marker": tuple(
                            f"marker-{index}" for index in range(len(marker_rows))
                        ),
                        "attribute": marker_columns,
                    },
                )
                return True
            return False

        if self.morphology.entity_click is None:
            raise ValueError("Morphology tool requires an authored entity click")
        context.on_entity_click(self.morphology.entity_click, handle_click)
        return _MorphologyToolRef(weights=weights, markers=markers)


def test_generic_hit_selection_is_not_an_entity_special_case():
    observed = []

    @dataclass(frozen=True, slots=True)
    class HitSelectionRef:
        panel: object
        selected: object
        click: object

    class HitSelection(cnv.Widget[HitSelectionRef]):
        def declare(self, context):
            surface = context.grid(
                "surface",
                values=np.asarray([[1.0]], dtype=np.float32),
            )
            target = context.hit_target("surface")
            selected = context.selection(
                "surface points",
                hit_target=target,
                item_kind="hit",
                multiple=True,
            )
            click = context.click(
                "surface",
                hit_target=target,
                result_kind="hit",
                selection=selected,
            )

            def observe(ctx, event):
                observed.append((ctx.click_id, ctx.click_value, event.gesture))

            context.on_click(click, observe)
            panel = context.view(
                "test_surface",
                "Surface",
                inputs={"surface": surface},
                hit_targets={"surface": target},
                selections={"points": selected},
                clicks={"surface": click},
            )
            return HitSelectionRef(panel, selected, click)

    inline._reset_authoring_app()
    source = cnv.source()
    authored = source.add(HitSelection())
    app = _lower(source)
    selection = app.selection(authored.selected.id)
    interaction = app.click(authored.click.id)

    assert selection.target_type == "hit_target"
    assert selection.target_id == authored.click.hit_target_id
    assert selection.item_kind == interaction.result_kind == "hit"

    backend = source._make_backend()
    backend.initialize(app)
    backend.take_outbound_messages()
    value = cnv.HitValue(
        primitive_id=4,
        world_position=(1.0, 2.0, 3.0),
        normal=(0.0, 0.0, 1.0),
        depth=0.25,
    )
    backend.handle(command_message(clicked(authored.click.id, value)))
    assert backend.values.get(authored.selected.id) == [value]
    assert observed[0][0] == authored.click.id
    assert observed[0][1] == value

    backend.handle(command_message(clicked(authored.click.id, value)))
    assert backend.values.get(authored.selected.id) == []


def test_pointcloud_fixture_respects_public_import_boundary():
    for path in (
        FIXTURE / "pointcloud.py",
        FIXTURE / "pointcloud_slice.py",
        FIXTURE / "pointcloud_vispy.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "compneurovis.inline" not in source
        assert "compneurovis.core" not in source
        assert "compneurovis.frontends.vispy." not in source


def test_app_local_widget_scripts_need_no_package_install():
    sys.path.insert(0, str(LOCAL_FIXTURE))
    sys.modules.pop("local_gauge", None)
    sys.modules.pop("local_gauge_vispy", None)
    try:
        local_gauge = importlib.import_module("local_gauge")
        assert "local_gauge_vispy" not in sys.modules

        inline._reset_authoring_app()
        source = cnv.source()
        panel = source.add(local_gauge.LocalGauge("Local", [0.2, 0.8]))
        cnv.layout(((panel,),))
        app = _lower(source)
        assert next(iter(app.view_catalog.views.values())).kind == "local_gauge"
        assert app.layout_catalog.active_layout().panels[0].kind == "local_gauge_panel"
        assert "local_gauge_vispy" not in sys.modules

        from compneurovis.frontends.vispy import load_vispy_plugins
        from compneurovis.frontends.vispy.registries.panel_hosts import _panel_host_factories

        load_vispy_plugins()
        assert "local_gauge_vispy" in sys.modules
        assert "local_gauge_panel" in _panel_host_factories
    finally:
        sys.path.remove(str(LOCAL_FIXTURE))
        sys.modules.pop("local_gauge", None)
        sys.modules.pop("local_gauge_vispy", None)
        try:
            from compneurovis.frontends.vispy.registries.panel_hosts import _panel_host_factories
            from compneurovis.frontends.vispy.plugins import (
                _loaded_local_plugins,
                _local_plugins,
            )

            _panel_host_factories.pop("local_gauge_panel", None)
            _local_plugins.pop("local_gauge_vispy:register", None)
            _loaded_local_plugins.discard("local_gauge_vispy:register")
        except ImportError:
            pass


def test_entry_point_plugin_discovery_is_recursion_safe(monkeypatch):
    from compneurovis.frontends.vispy import load_vispy_plugins
    from compneurovis.frontends.vispy import plugins

    calls = []

    class EntryPoint:
        group = plugins.PLUGIN_ENTRY_POINT_GROUP
        name = "recursive-fixture"
        value = "recursive_fixture:register"

        def load(self):
            def register():
                calls.append("register")
                load_vispy_plugins()

            return register

    class EntryPoints(tuple):
        def select(self, *, group):
            return self if group == plugins.PLUGIN_ENTRY_POINT_GROUP else ()

    identity = (
        "",
        plugins.PLUGIN_ENTRY_POINT_GROUP,
        "recursive-fixture",
        "recursive_fixture:register",
    )
    plugins._loaded_entry_points.discard(identity)
    plugins._loading_entry_points.discard(identity)
    monkeypatch.setattr(plugins, "entry_points", lambda: EntryPoints((EntryPoint(),)))
    try:
        load_vispy_plugins()
        assert calls == ["register"]
        assert identity in plugins._loaded_entry_points
        assert identity not in plugins._loading_entry_points
    finally:
        plugins._loaded_entry_points.discard(identity)
        plugins._loading_entry_points.discard(identity)


def test_local_plugin_discovery_is_recursion_safe_and_builtins_run_first(
    monkeypatch,
):
    from compneurovis.frontends.vispy import load_vispy_plugins
    from compneurovis.frontends.vispy import plugins
    from compneurovis.frontends.vispy.registries.renderers import _factories

    path = "recursive_local_fixture:register"
    calls = []

    class Module:
        @staticmethod
        def register():
            assert "line_plot" in _factories
            calls.append("register")
            load_vispy_plugins()

    class EntryPoints(tuple):
        def select(self, *, group):
            del group
            return ()

    plugins._local_plugins[path] = None
    plugins._loaded_local_plugins.discard(path)
    plugins._loading_local_plugins.discard(path)
    monkeypatch.setattr(plugins, "import_module", lambda name: Module)
    monkeypatch.setattr(plugins, "entry_points", lambda: EntryPoints())
    try:
        load_vispy_plugins()
        assert calls == ["register"]
        assert path in plugins._loaded_local_plugins
        assert path not in plugins._loading_local_plugins
    finally:
        plugins._local_plugins.pop(path, None)
        plugins._loaded_local_plugins.discard(path)
        plugins._loading_local_plugins.discard(path)


def test_entry_point_identity_includes_owning_distribution(monkeypatch):
    from compneurovis.frontends.vispy import load_vispy_plugins
    from compneurovis.frontends.vispy import plugins

    calls = []

    class Distribution:
        def __init__(self, name):
            self.name = name

    class EntryPoint:
        group = plugins.PLUGIN_ENTRY_POINT_GROUP
        name = "shared-name"
        value = "shared_module:register"

        def __init__(self, distribution):
            self.dist = Distribution(distribution)

        def load(self):
            distribution = self.dist.name

            def register():
                calls.append(distribution)

            return register

    class EntryPoints(tuple):
        def select(self, *, group):
            return self if group == plugins.PLUGIN_ENTRY_POINT_GROUP else ()

    identities = {
        (
            distribution,
            plugins.PLUGIN_ENTRY_POINT_GROUP,
            "shared-name",
            "shared_module:register",
        )
        for distribution in ("distribution-a", "distribution-b")
    }
    plugins._loaded_entry_points.difference_update(identities)
    plugins._loading_entry_points.difference_update(identities)
    monkeypatch.setattr(
        plugins,
        "entry_points",
        lambda: EntryPoints(
            (EntryPoint("distribution-a"), EntryPoint("distribution-b"))
        ),
    )
    try:
        load_vispy_plugins()
        assert calls == ["distribution-a", "distribution-b"]
        assert identities <= plugins._loaded_entry_points
    finally:
        plugins._loaded_entry_points.difference_update(identities)
        plugins._loading_entry_points.difference_update(identities)


def test_app_local_pointcloud_fixture_lowers_headless_and_discovers_plugin(
    monkeypatch,
):
    monkeypatch.syspath_prepend(str(FIXTURE))
    sys.modules.pop("pointcloud", None)
    sys.modules.pop("pointcloud_slice", None)
    sys.modules.pop("pointcloud_vispy", None)
    importlib.invalidate_caches()

    pointcloud = importlib.import_module("pointcloud")
    assert "pointcloud_vispy" not in sys.modules

    inline._reset_authoring_app()
    source = cnv.source()
    axis = source.dropdown(
        "slice_axis",
        label="Slice axis",
        options=("x", "y", "z"),
        default="z",
    )
    position = source.slider(
        "slice_position",
        label="Slice position",
        min=0.0,
        max=1.0,
        default=0.5,
    )
    thickness = source.slider(
        "slice_thickness",
        label="Slice thickness",
        min=0.0,
        max=1.0,
        default=0.6,
    )
    cloud = source.add(
        pointcloud.PointCloud3D(
            "External cloud",
            positions=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.5, 0.25],
                    [2.0, 1.0, 0.5],
                ],
                dtype=np.float32,
            ),
            values=np.array([0.1, 0.5, 0.9], dtype=np.float32),
            select_multiple=True,
        )
    )
    other_cloud = source.add(
        pointcloud.PointCloud3D(
            "Other external cloud",
            positions=np.array(
                [
                    [0.0, 1.0, 0.0],
                    [1.0, 1.5, 0.25],
                    [2.0, 2.0, 0.5],
                ],
                dtype=np.float32,
            ),
            values=np.array([0.9, 0.5, 0.1], dtype=np.float32),
        )
    )
    slice_data = source.add(
        pointcloud.PointCloudPlaneSlice(
            "Cloud slice",
            source=cloud,
            axis=axis,
            position=position,
            thickness=thickness,
            overlay={"color": "#ff9d00", "alpha": 0.2},
        )
    )
    scatter = source.add(
        pointcloud.Scatter2D(
            "Projected slice",
            source=slice_data,
        )
    )
    cnv.layout(
        (
            (cloud, other_cloud),
            (scatter, source.controls_panel),
        )
    )
    app = _lower(source)

    geometries = tuple(app.data.geometries.values())
    views = tuple(app.view_catalog.views.values())
    selections = tuple(app.interactions.selections.values())
    geometry = geometries[0]
    view = views[0]
    other_view = views[1]
    scatter_view = next(item for item in views if item.kind == "scatter_2d")
    operator = next(iter(app.view_catalog.operators.values()))
    contribution = next(iter(app.view_catalog.contributions.values()))
    assert isinstance(geometry, cnv.GeometrySpec)
    assert geometry.kind == "point_cloud"
    assert isinstance(view, cnv.ViewSpec)
    assert view.kind == "point_cloud_3d"
    assert view.geometries["points"] == geometry.id
    assert len(selections) == 2
    assert cloud.selected is not None
    assert other_cloud.selected is not None
    assert cloud.selected.id != other_cloud.selected.id
    assert view.selections["entities"] == cloud.selected.id
    assert other_view.selections["entities"] == other_cloud.selected.id
    assert isinstance(operator, cnv.OperatorSpec)
    assert operator.kind == "point_cloud_plane_slice"
    assert operator.inputs["values"] == cloud.values._field_id
    assert operator.geometries["points"] == cloud.geometry.id
    assert operator.properties["axis"].key == axis.value_key
    assert operator.properties["position"].key == position.value_key
    assert operator.properties["thickness"].key == thickness.value_key
    assert scatter_view.inputs["data"] == operator.id
    assert contribution.kind == "point_cloud_plane_slice_overlay"
    assert contribution.capability == "scene3d.layers/v1"
    assert contribution.inputs["slice"] == operator.id
    assert contribution.geometries["points"] == cloud.geometry.id
    cloud_panel = app.layout_catalog.active_layout().panel_for_view(view.id)
    assert cloud_panel is not None
    assert contribution.id in cloud_panel.contribution_ids

    backend = source._make_backend()
    backend.initialize(app)
    backend.take_outbound_messages()
    backend.handle(command_message(clicked(cloud.entity_click.id, "1")))
    assert backend.values.get(cloud.selected.id) == ["1"]
    assert backend.values.get(other_cloud.selected.id) == []
    update = backend.take_outbound_messages()[-1].payload
    assert update.updates == {cloud.selected.id: ["1"]}
    backend.handle(command_message(clicked(cloud.entity_click.id, "1")))
    assert backend.values.get(cloud.selected.id) == []
    assert backend.values.get(other_cloud.selected.id) == []

    inline._reset_authoring_app()
    first_source = cnv.source()
    first = first_source.add(
        pointcloud.PointCloud3D(
            "Same local name",
            positions=np.zeros((2, 3), dtype=np.float32),
        )
    )
    first_slice = first_source.add(
        pointcloud.PointCloudPlaneSlice(
            "Same local slice",
            source=first,
        )
    )
    second_source = cnv.source()
    second = second_source.add(
        pointcloud.PointCloud3D(
            "Same local name",
            positions=np.ones((2, 3), dtype=np.float32),
        )
    )
    second_slice = second_source.add(
        pointcloud.PointCloudPlaneSlice(
            "Same local slice",
            source=second,
        )
    )
    assert first.selected is not None and second.selected is not None
    assert first.selected.id == second.selected.id
    composed_plan = build_multi_source_run_plan((first_source, second_source))
    composed = composed_plan.app_spec
    scoped_selections = tuple(composed.iter_selections())
    assert [ref.fragment_id for ref, _ in scoped_selections] == [
        "source0",
        "source1",
    ]
    assert scoped_selections[0][0].id == scoped_selections[1][0].id
    assert scoped_selections[0][0] != scoped_selections[1][0]
    scoped_hit_targets = tuple(composed.iter_hit_targets())
    assert [ref.fragment_id for ref, _ in scoped_hit_targets] == [
        "source0",
        "source1",
    ]
    assert scoped_hit_targets[0][0].id == scoped_hit_targets[1][0].id
    assert scoped_hit_targets[0][0] != scoped_hit_targets[1][0]
    assert first_slice._field_id == second_slice._field_id
    scoped_operators = tuple(composed.iter_operator_specs())
    assert [ref.fragment_id for ref, _ in scoped_operators] == [
        "source0",
        "source1",
    ]
    assert scoped_operators[0][0].id == scoped_operators[1][0].id
    assert scoped_operators[0][0] != scoped_operators[1][0]
    scoped_contributions = tuple(composed.iter_visual_contributions())
    assert [ref.fragment_id for ref, _ in scoped_contributions] == [
        "source0",
        "source1",
    ]
    assert scoped_contributions[0][0].id == scoped_contributions[1][0].id
    assert scoped_contributions[0][0] != scoped_contributions[1][0]
    assert not any(
        route.match.message_type == "clicked"
        for route in composed_plan.routing.routes
    )
    process_context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = process_context.Pipe()
    process = process_context.Process(
        target=_inspect_pipe_payload,
        args=(child_connection,),
    )
    process.start()
    child_connection.close()
    try:
        parent_connection.send(app)
        assert parent_connection.poll(10), "Timed out waiting for the pipe receiver"
        transported = parent_connection.recv()
    finally:
        parent_connection.close()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
    assert process.exitcode == 0
    assert transported == (
        True,
        "point_cloud",
        True,
        "point_cloud_plane_slice",
        True,
        True,
        True,
        True,
        False,
    )
    assert "pointcloud_vispy" not in sys.modules

    from compneurovis.frontends.vispy import (
        OperatorResolveContext,
        load_vispy_plugins,
        register_scene_layer,
    )
    from compneurovis.frontends.vispy.registries.operators import operator_adapter
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner
    from compneurovis.frontends.vispy.registries.scene_layers import (
        create_scene_layers,
        scene_layer_for_target,
    )
    from compneurovis.frontends.vispy.registries.visual_contributions import (
        SCENE_3D_LAYER_CAPABILITY,
        visual_contribution_renderer,
    )

    load_vispy_plugins()
    assert "pointcloud_vispy" in sys.modules
    assert scene_layer_for_target("point_cloud_3d") == "point_cloud_3d"
    assert (
        visual_contribution_renderer(
            SCENE_3D_LAYER_CAPABILITY,
            "point_cloud_plane_slice_overlay",
        ).factory
        is not None
    )

    projection = cnv.AppProjection(app)
    values = backend.values.snapshot()
    resolve_context = OperatorResolveContext(
        get_field=lambda field_id: projection.field(field_id),
        get_geometry=lambda geometry_id: app.geometry(geometry_id),
        values=values,
        fragment_id=cnv.DEFAULT_FRAGMENT_ID,
    )
    projected = operator_adapter(operator).resolve_field(
        operator,
        resolve_context,
    )
    assert projected is not None
    assert projected.dims == ("point", "component")
    assert projected.coords["component"].tolist() == ["u", "v", "value"]
    assert projected.attrs["schema"] == "point_cloud_plane_slice/v1"
    assert projected.attrs["slice_axis"] == "z"
    np.testing.assert_allclose(
        projected.values,
        np.array([[1.0, 0.5, 0.5]], dtype=np.float32),
    )
    assert projected.coords["point"].tolist() == ["1"]
    moved_values = dict(values)
    moved_values[position.value_key] = 1.0
    moved = operator_adapter(operator).resolve_field(
        operator,
        OperatorResolveContext(
            get_field=resolve_context.get_field,
            get_geometry=resolve_context.get_geometry,
            values=moved_values,
            fragment_id=resolve_context.fragment_id,
        ),
    )
    assert moved is not None
    np.testing.assert_allclose(
        moved.values,
        np.array([[2.0, 1.0, 0.9]], dtype=np.float32),
    )
    assert moved.coords["point"].tolist() == ["2"]

    planner = RefreshPlanner(app, app.layout_catalog.active_layout)
    position_targets = planner.targets_for_value_change(position.value_key)
    assert any(
        target.kind == "visual_contribution"
        and target.contribution_id == cnv.app_ref(contribution.id)
        and target.panel_id == cloud_panel.id
        for target in position_targets
    )
    assert any(
        target.kind == "view" and str(target.view_id) == scatter_view.id
        for target in position_targets
    )

    pointcloud_vispy = sys.modules["pointcloud_vispy"]

    class FakeMarkers:
        def set_data(self, **kwargs):
            self.last = kwargs

    class FakeCanvas:
        def render(self, **kwargs):
            del kwargs
            return np.array([[[2, 0, 0]]], dtype=np.uint8)

    visual = object.__new__(pointcloud_vispy.PointCloudVisual)
    visual._markers = FakeMarkers()
    visual._positions = np.zeros((3, 3), dtype=np.float32)
    visual._entity_ids = ("0", "1", "2")
    visual._colors = np.ones((3, 4), dtype=np.float32)
    visual._point_size = 8.0
    hit = visual.hit_test(10, 20, FakeCanvas())
    assert hit.primitive_id == 1
    assert hit.target_role == "entities"
    assert visual.value_for_hit(hit, "entity") == "1"

    constructed: list[str] = []

    class FakeVisual:
        def refresh_for_target(self, kind, view, ctx):
            del kind, view, ctx

        def clear(self):
            pass

        def hit_test(self, xf, yf, canvas):
            del xf, yf, canvas
            return None

        def value_for_hit(self, hit, result_kind):
            del hit, result_kind
            return None

    def first_factory(view, *, panel_id=None):
        del view, panel_id
        constructed.append("first")
        return FakeVisual()

    def second_factory(view, *, panel_id=None):
        del view, panel_id
        constructed.append("second")
        return FakeVisual()

    register_scene_layer(
        "conformance_first",
        first_factory,
        from_view=lambda view: view,
        patch={"conformance_first_target": None},
        targets=("conformance_first_target",),
    )
    register_scene_layer(
        "conformance_second",
        second_factory,
        from_view=lambda view: view,
        patch={"conformance_second_target": None},
        targets=("conformance_second_target",),
    )
    created = create_scene_layers(
        object(),
        kind="conformance_first",
        panel_id="fixture-panel",
    )
    assert tuple(created) == ("conformance_first",)
    assert constructed == ["first"]

    with pytest.raises(ValueError, match="already owned"):
        register_scene_layer(
            "conformance_collision",
            second_factory,
            from_view=lambda view: view,
            patch={"conformance_first_target": None},
            targets=("conformance_first_target",),
        )
    with pytest.raises(LookupError, match="No Vispy Scene3D layer"):
        create_scene_layers(object(), kind="conformance_missing")

    register_scene_layer(
        "conformance_incomplete",
        lambda view, panel_id=None: object(),
        from_view=lambda view: view,
        patch={"conformance_incomplete": None},
    )
    with pytest.raises(TypeError, match="must implement"):
        create_scene_layers(object(), kind="conformance_incomplete")


def test_scene_layer_registration_is_atomic_validated_and_defensive():
    from compneurovis.frontends.vispy import register_scene_layer
    from compneurovis.frontends.vispy import refresh_planning
    from compneurovis.frontends.vispy.registries import render_configs, scene_layers

    kind = "atomic_scene_fixture"
    target = "atomic_scene_target"

    def factory(view, *, panel_id=None):
        del view, panel_id
        return object()

    def builder(view):
        return view

    def conflicting_builder(view):
        return view

    def clear_fixture():
        scene_layers._SCENE_LAYER_FACTORIES.pop(kind, None)
        scene_layers._SCENE_LAYER_TARGETS.pop(kind, None)
        scene_layers._SCENE_LAYER_REGISTRATIONS.pop(kind, None)
        scene_layers._rebuild_target_index()
        render_configs._VIEW_RENDER_CONFIGS.pop(kind, None)
        refresh_planning._VIEW_REFRESH_REGISTRATIONS.pop(kind, None)
        refresh_planning._VIEW_PATCH_SCHEMA.pop(kind, None)
        refresh_planning._VIEW_VALUE_BINDING_SCHEMA.pop(kind, None)
        refresh_planning._VIEW_FULL_REFRESH_KINDS.pop(kind, None)
        refresh_planning._VIEW_FIELD_ID_PROPS.pop(kind, None)
        refresh_planning._VIEW_FIELD_REPLACE_HOOKS.pop(kind, None)

    clear_fixture()
    try:
        render_configs.register_view_render_config(kind, conflicting_builder)
        with pytest.raises(ValueError, match="already registered"):
            register_scene_layer(
                kind,
                factory,
                from_view=builder,
                targets=(target,),
                patch={target: None},
            )
        assert kind not in scene_layers._SCENE_LAYER_REGISTRATIONS
        assert target not in scene_layers._TARGET_TO_LAYER
        assert kind not in refresh_planning._VIEW_REFRESH_REGISTRATIONS
        assert render_configs._VIEW_RENDER_CONFIGS[kind] is conflicting_builder

        render_configs._VIEW_RENDER_CONFIGS.pop(kind)
        patch_properties = {"color"}
        patch = {target: patch_properties}
        value_properties = {"alpha"}
        value_binding = {target: value_properties}
        field_id_props = {"field_id": target}
        register_scene_layer(
            kind,
            factory,
            from_view=builder,
            targets=(target,),
            patch=patch,
            value_binding=value_binding,
            full_refresh=(target,),
            field_id_props=field_id_props,
        )

        patch_properties.add("later")
        patch[target] = None
        value_properties.add("later")
        field_id_props["other"] = target
        registration = scene_layers._SCENE_LAYER_REGISTRATIONS[kind]
        assert registration.patch[target] == frozenset({"color"})
        assert registration.value_binding[target] == frozenset({"alpha"})
        assert dict(registration.field_id_props) == {"field_id": target}
        assert (
            refresh_planning._VIEW_PATCH_SCHEMA[kind][target]
            == frozenset({"color"})
        )

        with pytest.raises(ValueError, match="not declared"):
            register_scene_layer(
                "invalid_scene_fixture",
                factory,
                from_view=builder,
                targets=("declared",),
                patch={"undeclared": None},
            )
    finally:
        clear_fixture()


def test_external_morphology_tool_owns_state_layers_and_click_policy():
    inline._reset_authoring_app()
    source = cnv.source()
    mode = source.dropdown(
        "tool mode",
        label="Tool mode",
        options=("select", "paint", "mark"),
        default="select",
    )
    weight = source.slider(
        "paint weight",
        label="Paint weight",
        min=0.0,
        max=1.0,
        default=0.75,
    )
    entity_ids = ("soma", "dendrite")
    geometry = cnv.MorphologyGeometry(
        id="external_morphology",
        positions=np.asarray(
            [[0.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32
        ),
        orientations=np.asarray([np.eye(3), np.eye(3)], dtype=np.float32),
        radii=np.asarray([1.0, 0.5], dtype=np.float32),
        lengths=np.asarray([2.0, 3.0], dtype=np.float32),
        entity_ids=entity_ids,
        section_names=entity_ids,
        xlocs=np.asarray([0.5, 0.5], dtype=np.float32),
    )
    morphology = source.morphology(
        geometry,
        name="External morphology",
        values=np.asarray([-65.0, -60.0], dtype=np.float32),
        selectable=True,
    )
    tool = source.add(
        _MorphologyTool(
            morphology,
            mode=mode,
            weight=weight,
            entity_ids=entity_ids,
        )
    )
    app = _lower(source)

    assert morphology.geometry.id in app.data.geometries
    assert morphology.color is not None
    assert morphology.color._field_id in app.data.fields
    contributions = tuple(app.view_catalog.contributions.values())
    assert {item.kind for item in contributions} == {
        "test_weight_layer",
        "test_marker_layer",
    }
    assert all(
        item.geometries["morphology"] == morphology.geometry.id
        for item in contributions
    )

    backend = source._make_backend()
    backend.initialize(app)
    backend.take_outbound_messages()

    backend.handle(command_message(ValueChange({mode.value_key: "paint"})))
    backend.take_outbound_messages()
    backend.handle(
        command_message(clicked(morphology.entity_click.id, "dendrite"))
    )
    assert backend.values.get(morphology.selected.id) == []
    paint_update = backend.take_outbound_messages()[-1].payload
    assert isinstance(paint_update, FieldReplace)
    assert paint_update.field_id == tool.weights._field_id
    np.testing.assert_allclose(paint_update.values, [0.0, 0.75])

    backend.handle(command_message(ValueChange({mode.value_key: "mark"})))
    backend.take_outbound_messages()
    backend.handle(command_message(clicked(morphology.entity_click.id, "soma")))
    assert backend.values.get(morphology.selected.id) == []
    marker_update = backend.take_outbound_messages()[-1].payload
    assert isinstance(marker_update, FieldReplace)
    assert marker_update.field_id == tool.markers._field_id
    assert marker_update.values.shape == (1, 8)
    assert tuple(marker_update.coords["marker"]) == ("marker-0",)
    np.testing.assert_allclose(marker_update.values[0, :3], [0.0, 0.0, 0.0])

    backend.handle(command_message(ValueChange({mode.value_key: "select"})))
    backend.take_outbound_messages()
    backend.handle(command_message(clicked(morphology.entity_click.id, "soma")))
    assert backend.values.get(morphology.selected.id) == ["soma"]


def test_app_local_morphology_painting_updates_only_target_color_field(monkeypatch):
    monkeypatch.syspath_prepend(str(PAINT_FIXTURE))
    sys.modules.pop("morphology_painting", None)
    painting = importlib.import_module("morphology_painting")

    inline._reset_authoring_app()
    source = cnv.source()
    brush = source.slider(
        "brush",
        label="Brush",
        min=0.0,
        max=1.0,
        default=0.25,
    )
    paint_mode = source.checkbox("paint mode", label="Paint", default=False)
    entity_ids = ("soma", "dendrite")
    geometry = cnv.MorphologyGeometry(
        id="paint_fixture",
        positions=np.asarray(
            [[0.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32
        ),
        orientations=np.asarray([np.eye(3), np.eye(3)], dtype=np.float32),
        radii=np.asarray([1.0, 0.5], dtype=np.float32),
        lengths=np.asarray([2.0, 3.0], dtype=np.float32),
        entity_ids=entity_ids,
        section_names=entity_ids,
        xlocs=np.asarray([0.5, 0.5], dtype=np.float32),
    )
    initial = np.zeros(2, dtype=np.float32)
    morphology = source.morphology(
        geometry,
        values=initial,
        selectable=True,
    )
    painted = source.add(
        painting.MorphologyPainting(
            morphology=morphology,
            entity_ids=entity_ids,
            initial_values=initial,
            brush_value=brush,
            enabled=paint_mode,
        )
    )
    app = _lower(source)
    pointer_ref, pointer_spec = next(app.iter_pointer_interactions())
    assert pointer_spec.hit_target_id == morphology.entity_click.hit_target_id
    assert pointer_spec.enabled.key == paint_mode.value_key

    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow

    class PointerWindow:
        app_spec = app

        def __init__(self, enabled):
            self.enabled = enabled

        def value_snapshot(self):
            return {cnv.app_ref(paint_mode.value_key): self.enabled}

    morphology_view = next(
        view
        for view in app.view_catalog.views.values()
        if view.clicks.get("entities") == morphology.entity_click.id
    )
    assert (
        VispyFrontendWindow._resolve_pointer_interaction(
            PointerWindow(False), morphology_view.id, "entities", "primary"
        )
        is None
    )
    claim = VispyFrontendWindow._resolve_pointer_interaction(
        PointerWindow(True), morphology_view.id, "entities", "primary"
    )
    assert claim.owner == pointer_ref
    assert claim.result_kind == "entity"

    backend = source._make_backend()
    backend.initialize(app)
    backend.take_outbound_messages()

    backend.handle(
        command_message(
            ValueChange({brush.value_key: 0.6, paint_mode.value_key: True})
        )
    )
    backend.take_outbound_messages()
    backend.handle(
        command_message(
            PointerInteractionEvent(
                interaction_id=pointer_ref.id,
                pointer=cnv.PointerEvent(
                    sample=cnv.PointerSample(
                        pointer_id="mouse:0",
                        phase="press",
                        pointer_type="mouse",
                        position=(0.5, 0.5),
                        button="primary",
                        buttons=("primary",),
                    ),
                    hits=(
                        cnv.HitRecord(
                            target_role="entities",
                            primitive_id="dendrite",
                        ),
                    ),
                ),
                value="dendrite",
            )
        )
    )

    assert painted is morphology.color
    assert backend.values.get(morphology.selected.id) == []
    update = backend.take_outbound_messages()[-1].payload
    assert isinstance(update, FieldReplace)
    assert update.field_id == morphology.color._field_id
    np.testing.assert_allclose(update.values, [0.0, 0.6])
    assert "compneurovis.inline" not in (
        PAINT_FIXTURE / "morphology_painting.py"
    ).read_text(encoding="utf-8")
