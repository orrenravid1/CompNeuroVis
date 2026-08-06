from __future__ import annotations

import importlib
import importlib.metadata
import multiprocessing
import shutil
import site
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import compneurovis as cnv
import compneurovis.inline as inline
from compneurovis.core.messages import EntityClicked, command_message
from compneurovis._source_runtime import build_multi_source_run_plan


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "extensions" / "cnv_pointcloud_demo"
LOCAL_FIXTURE = ROOT / "examples" / "extensions" / "local_gauge"


def _lower(source):
    source._panel_grid = inline._app._panel_grid
    backend = source._make_backend()
    return source._build_app_spec_for_backend(backend)


def _inspect_pipe_payload(connection):
    app = connection.recv()
    geometry = next(iter(app.data.geometries.values()))
    operator = next(iter(app.view_catalog.operators.values()))
    scatter = next(
        view for view in app.view_catalog.views.values() if view.kind == "scatter_2d"
    )
    connection.send(
        (
            isinstance(geometry, cnv.ExtensionGeometrySpec),
            geometry.kind,
            isinstance(operator, cnv.ExtensionOperatorSpec),
            operator.kind,
            operator.geometries["points"] == geometry.id,
            scatter.inputs["data"] == operator.id,
            "cnv_pointcloud_demo" in sys.modules,
        )
    )
    connection.close()


def test_pointcloud_fixture_respects_public_import_boundary():
    package = FIXTURE / "src" / "cnv_pointcloud_demo"
    for path in package.glob("*.py"):
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

        inline._reset_inline_session()
        source = cnv.source()
        panel = source.add(local_gauge.LocalGauge("Local", [0.2, 0.8]))
        cnv.layout(((panel,),))
        app = _lower(source)
        assert next(iter(app.view_catalog.views.values())).kind == "local_gauge"
        assert "local_gauge_vispy" not in sys.modules

        from compneurovis.frontends.vispy import load_vispy_plugins
        from compneurovis.frontends.vispy.renderers.registry import _factories

        load_vispy_plugins()
        assert "local_gauge_vispy" in sys.modules
        assert "local_gauge" in _factories
    finally:
        sys.path.remove(str(LOCAL_FIXTURE))
        sys.modules.pop("local_gauge", None)
        sys.modules.pop("local_gauge_vispy", None)
        try:
            from compneurovis.frontends.vispy.renderers.registry import _factories
            from compneurovis.frontends.vispy.plugins import (
                _loaded_local_plugins,
                _local_plugins,
            )

            _factories.pop("local_gauge", None)
            _local_plugins.pop("local_gauge_vispy:register", None)
            _loaded_local_plugins.discard("local_gauge_vispy:register")
        except ImportError:
            pass


def test_installed_pointcloud_fixture_lowers_headless_and_discovers_plugin(
    tmp_path,
):
    fixture_copy = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture_copy)
    target = tmp_path / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(target),
            str(fixture_copy),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    site.addsitedir(str(target))
    importlib.invalidate_caches()

    distributions = tuple(importlib.metadata.distributions(path=[str(target)]))
    distribution = next(
        item for item in distributions if item.metadata["Name"] == "cnv-pointcloud-demo"
    )
    plugin = next(
        item
        for item in distribution.entry_points
        if item.group == "compneurovis.vispy_plugins"
    )
    assert plugin.name == "pointcloud"
    assert not any(
        item.group == "compneurovis.vispy_renderers"
        for item in distribution.entry_points
    )

    pointcloud = importlib.import_module("cnv_pointcloud_demo")
    assert "cnv_pointcloud_demo.vispy" not in sys.modules

    inline._reset_inline_session()
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
    assert isinstance(geometry, cnv.ExtensionGeometrySpec)
    assert geometry.kind == "point_cloud"
    assert isinstance(view, cnv.ExtensionViewSpec)
    assert view.kind == "point_cloud_3d"
    assert view.geometries["points"] == geometry.id
    assert len(selections) == 2
    assert cloud.selected is not None
    assert other_cloud.selected is not None
    assert cloud.selected.id != other_cloud.selected.id
    assert view.selections["entities"] == cloud.selected.id
    assert other_view.selections["entities"] == other_cloud.selected.id
    assert isinstance(operator, cnv.ExtensionOperatorSpec)
    assert operator.kind == "point_cloud_plane_slice"
    assert operator.inputs["values"] == cloud.values._field_id
    assert operator.geometries["points"] == cloud.geometry.id
    assert operator.properties["axis"].key == axis.value_key
    assert operator.properties["position"].key == position.value_key
    assert operator.properties["thickness"].key == thickness.value_key
    assert scatter_view.inputs["data"] == operator.id
    cloud_panel = app.layout_catalog.active_layout().panel_for_view(view.id)
    assert cloud_panel is not None
    assert operator.id in cloud_panel.operator_ids

    backend = source._make_backend()
    backend.initialize(app)
    backend.take_outbound_messages()
    backend.handle(command_message(EntityClicked(cloud.selected.id, "1")))
    assert backend.values.get(cloud.selected.id) == ["1"]
    assert backend.values.get(other_cloud.selected.id) == []
    update = backend.take_outbound_messages()[-1].payload
    assert update.updates == {cloud.selected.id: ["1"]}
    backend.handle(command_message(EntityClicked(cloud.selected.id, "1")))
    assert backend.values.get(cloud.selected.id) == []
    assert backend.values.get(other_cloud.selected.id) == []

    inline._reset_inline_session()
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
    assert first_slice._field_id == second_slice._field_id
    scoped_operators = tuple(composed.iter_operator_specs())
    assert [ref.fragment_id for ref, _ in scoped_operators] == [
        "source0",
        "source1",
    ]
    assert scoped_operators[0][0].id == scoped_operators[1][0].id
    assert scoped_operators[0][0] != scoped_operators[1][0]
    assert not any(
        route.match.message_type == "entity_clicked"
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
        False,
    )
    assert "cnv_pointcloud_demo.vispy" not in sys.modules

    from compneurovis.frontends.vispy import (
        OperatorResolveContext,
        load_vispy_plugins,
        register_3d_visual,
    )
    from compneurovis.frontends.vispy.operator_adapters import operator_adapter
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner
    from compneurovis.frontends.vispy.view3d.visuals import (
        create_3d_visuals,
        visual_key_for_target,
    )

    load_vispy_plugins()
    assert "cnv_pointcloud_demo.vispy" in sys.modules
    assert visual_key_for_target("point_cloud_3d") == "point_cloud_3d"
    assert visual_key_for_target("point_cloud_plane_slice_overlay") == "point_cloud_3d"

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
        target.kind == "point_cloud_plane_slice_overlay"
        and str(target.view_id) == view.id
        for target in position_targets
    )
    assert any(
        target.kind == "extension" and str(target.view_id) == scatter_view.id
        for target in position_targets
    )

    pointcloud_vispy = sys.modules["cnv_pointcloud_demo.vispy"]

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
    assert visual.pick_entity(10, 20, FakeCanvas()) == "1"

    constructed: list[str] = []

    class FakeVisual:
        def refresh_for_target(self, kind, view, ctx):
            del kind, view, ctx

        def clear(self):
            pass

        def pick_entity(self, xf, yf, canvas):
            del xf, yf, canvas
            return None

    def first_factory(view, *, panel_id=None):
        del view, panel_id
        constructed.append("first")
        return FakeVisual()

    def second_factory(view, *, panel_id=None):
        del view, panel_id
        constructed.append("second")
        return FakeVisual()

    register_3d_visual(
        "conformance_first",
        first_factory,
        from_extension=lambda view: view,
        patch={"conformance_first_target": None},
        targets=("conformance_first_target",),
    )
    register_3d_visual(
        "conformance_second",
        second_factory,
        from_extension=lambda view: view,
        patch={"conformance_second_target": None},
        targets=("conformance_second_target",),
    )
    created = create_3d_visuals(
        object(),
        kind="conformance_first",
        panel_id="fixture-panel",
    )
    assert tuple(created) == ("conformance_first",)
    assert constructed == ["first"]

    with pytest.raises(ValueError, match="already owned"):
        register_3d_visual(
            "conformance_collision",
            second_factory,
            from_extension=lambda view: view,
            patch={"conformance_first_target": None},
            targets=("conformance_first_target",),
        )
    with pytest.raises(LookupError, match="No Vispy 3-D visual"):
        create_3d_visuals(object(), kind="conformance_missing")

    register_3d_visual(
        "conformance_incomplete",
        lambda view, panel_id=None: object(),
        from_extension=lambda view: view,
        patch={"conformance_incomplete": None},
    )
    with pytest.raises(TypeError, match="must implement"):
        create_3d_visuals(object(), kind="conformance_incomplete")
