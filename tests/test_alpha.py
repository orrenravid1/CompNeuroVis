from __future__ import annotations

import runpy
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest

import compneurovis as cnv
import compneurovis.inline as inline
from _click_fixtures import clicked
from compneurovis.core import (
    AppFragmentSpec,
    AppRef,
    AppSpec,
    GeometrySpec,
    OperatorSpec,
    ViewSpec,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ViewCatalog,
    build_default_layout,
)


def _lower(source):
    source._panel_grid = inline._current_authoring_app()._panel_grid
    backend = source._make_backend()
    return source._build_app_spec_for_backend(backend)


def test_public_alpha_surface():
    assert all(
        hasattr(cnv, name) for name in ("source", "layout", "show", "neuron", "jaxley")
    )
    assert all(not hasattr(cnv, name) for name in ("compose", "remote", "remote_actor"))
    assert callable(cnv.experimental.compose)
    assert cnv.MorphologyGeometry.__module__ == "compneurovis.geometries.morphology"
    assert not hasattr(cnv.widgets, "MorphologyGeometry")


def test_widget_registry_rejects_non_callable_factories():
    with pytest.raises(TypeError, match="must be callable"):
        cnv.register_widget("invalid_widget_factory", None)


def test_explicit_inline_app_is_isolated_from_ambient_authoring():
    inline._reset_authoring_app()
    explicit_app = inline.InlineApp()
    explicit_source = explicit_app.source()

    assert explicit_app._sources == [explicit_source]
    assert inline._current_authoring_app()._sources == []

    ambient_source = cnv.source()
    assert inline._current_authoring_app()._sources == [ambient_source]
    assert explicit_app._sources == [explicit_source]


def test_core_layout_and_reference_contracts():
    layouts = LayoutCatalog(
        layouts={"compact": LayoutSpec(), "wide": LayoutSpec()},
        active="wide",
    )
    assert layouts.active == "wide"

    # A view declares its own panel kind; build_default_layout makes a panel of
    # that kind. Bars use the ordinary standalone host.
    view = ViewSpec(id="rates", kind="bar_plot")
    default_layout = build_default_layout(views={view.id: view})
    assert [(panel.id, panel.kind) for panel in default_layout.panels] == [
        ("rates-panel", "standalone")
    ]

    assert AppRef("field", fragment_id="source").flat_id() == "source:field"
    with pytest.raises(ValueError, match="cannot contain"):
        AppRef("source:field")


def test_default_layout_requires_explicit_non_view_panel_host_kind():
    view = ViewSpec(id="trace", kind="line_plot", panel_kind="plot_host")
    interaction_panel = PanelSpec(
        id="simulation-tools",
        kind="third_party_control_rack",
        control_ids=("gain",),
        action_ids=("reset",),
    )

    layout = build_default_layout(
        views={view.id: view},
        additional_panels=(interaction_panel,),
    )

    assert layout.panel("simulation-tools") is interaction_panel
    assert layout.panel("simulation-tools").kind == "third_party_control_rack"
    assert layout.panel_grid == (("trace-panel",), ("simulation-tools",))
    assert all(panel.kind != "controls" for panel in layout.panels)


def test_fragment_layouts_are_validated():
    invalid_fragment = AppFragmentSpec(
        id="source",
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(
                panels=(
                    PanelSpec(
                        id="trace-panel",
                        kind="line_plot",
                        view_ids=("missing",),
                    ),
                ),
                panel_grid=(("trace-panel",),),
            )
        ),
    )

    with pytest.raises(ValueError, match="source:default"):
        AppSpec(fragments={"source": invalid_fragment})


def test_neutral_operator_preserves_cross_fragment_input_scope():
    source_fragment = AppFragmentSpec(
        id="source",
        data=cnv.DataCatalog(
            fields={
                "samples": cnv.FieldSpec(
                    id="samples",
                    initial_values=np.array([1.0, 2.0], dtype=np.float32),
                    dims=("item",),
                    coords={"item": np.array([0, 1], dtype=np.float32)},
                )
            },
            geometries={
                "points": cnv.GeometrySpec(
                    id="points",
                    kind="test_points",
                    data={
                        "positions": np.zeros((2, 3), dtype=np.float32),
                    },
                ),
            },
        ),
    )
    operator = cnv.OperatorSpec(
        id="project",
        kind="identity",
        inputs={"source": AppRef("samples", fragment_id="source")},
        geometries={"domain": AppRef("points", fragment_id="source")},
    )
    view = ViewSpec(
        id="projected",
        kind="test_view",
        inputs={"data": "project"},
    )
    consumer_fragment = AppFragmentSpec(
        id="consumer",
        view_catalog=ViewCatalog(
            views={view.id: view},
            operators={operator.id: operator},
        ),
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(
                panels=(
                    PanelSpec(
                        id="projected-panel",
                        kind=view.panel_kind,
                        view_ids=(view.id,),
                    ),
                ),
                panel_grid=(("projected-panel",),),
            )
        ),
    )

    app = AppSpec(
        fragments={
            source_fragment.id: source_fragment,
            consumer_fragment.id: consumer_fragment,
        }
    )
    resolved = app.fragment("consumer").view_catalog.operators["project"]
    assert resolved.inputs["source"] == AppRef(
        "samples",
        fragment_id="source",
    )
    assert resolved.geometries["domain"] == AppRef(
        "points",
        fragment_id="source",
    )

    invalid_operator = cnv.OperatorSpec(
        id="invalid",
        kind="identity",
        geometries={"domain": AppRef("missing", fragment_id="source")},
    )
    invalid_fragment = AppFragmentSpec(
        id="invalid-consumer",
        view_catalog=ViewCatalog(
            operators={invalid_operator.id: invalid_operator},
        ),
    )
    with pytest.raises(ValueError, match="references unknown geometry"):
        AppSpec(
            fragments={
                source_fragment.id: source_fragment,
                invalid_fragment.id: invalid_fragment,
            }
        )


def test_inline_authoring_builds_one_integrated_app_spec():
    inline._reset_authoring_app()
    state = {"time": 0.0, "gain": 1.0}

    def step(ctx):
        state["time"] += 1.0

    def set_gain(ctx, value):
        state["gain"] = float(value)

    source = cnv.source(step)
    trace = source.line(
        "Signal",
        read=lambda: state["gain"],
        x=lambda: state["time"],
    )
    bars = source.bar(
        "Rates",
        values=np.array([1.0, 2.0], dtype=np.float32),
        series=("A", "B"),
    )
    surface = source.surface(
        "Surface",
        values=np.zeros((3, 4), dtype=np.float32),
        x=np.arange(4, dtype=np.float32),
        y=np.arange(3, dtype=np.float32),
    )
    source.slider(
        "gain",
        label="Gain",
        get=lambda: state["gain"],
        set=set_gain,
        min=0.0,
        max=2.0,
    )
    source.button("reset", label="Reset", fn=lambda ctx: ctx.reset())

    cnv.layout(((trace, surface), (bars, source.controls_panel)))
    app_spec = _lower(source)

    views = tuple(app_spec.view_catalog.views.values())
    # A ``read=`` series line is now a first-class canonical view (rendered via
    # the same registry a third-party widget uses), not a typed LinePlotRenderConfig.
    assert any(
        isinstance(view, ViewSpec) and view.kind == "line_plot"
        for view in views
    )
    assert any(
        isinstance(view, ViewSpec) and view.kind == "bar_plot"
        for view in views
    )
    assert any(
        isinstance(view, ViewSpec) and view.kind == "surface" for view in views
    )
    assert len(app_spec.interactions.controls) == 1
    assert next(iter(app_spec.interactions.controls.values())).label == "Gain"
    assert len(app_spec.interactions.actions) == 1
    assert next(iter(app_spec.interactions.actions.values())).label == "Reset"
    assert app_spec.layout_catalog.active_layout().panel_grid == (
        (trace.id, surface.id),
        (bars.id, source.controls_panel.id),
    )


def test_line_declares_generic_field_retention():
    from compneurovis.backends.compartment import resolved_field_max_samples

    inline._reset_authoring_app()
    source = cnv.source()
    line = source.line(
        "Signal",
        read=lambda: 0.0,
        rolling_window=12.5,
    )
    cnv.layout(((line,),))

    app = _lower(source)
    field_spec = app.data.fields[line.field_id]
    line_view = next(
        view
        for view in app.view_catalog.views.values()
        if isinstance(view, ViewSpec) and view.kind == "line_plot"
    )
    assert line_view.max_refresh_hz == 0.0
    assert field_spec.retention == (
        cnv.FieldRetentionSpec(append_dim="time", min_duration=12.5),
    )
    assert resolved_field_max_samples(
        app,
        field_id=line.field_id,
        append_dim="time",
        default=10,
        step=0.5,
    ) == 26


def test_surface_field_is_the_single_owner_of_grid_coordinates():
    """Surface scene geometry comes from its field, with no duplicate grid spec."""
    from multiprocessing.reduction import ForkingPickler

    from compneurovis.components.surface.data import (
        surface_scene_from_field,
    )

    inline._reset_authoring_app()
    x = np.array([-2.0, 0.5, 4.0], dtype=np.float32)
    y = np.array([10.0, 13.0], dtype=np.float32)
    values = np.arange(6, dtype=np.float32).reshape(2, 3)

    source = cnv.source()
    surface_ref = source.surface(
        "Offset grid",
        values=values,
        x=x,
        y=y,
        x_dim="longitude",
        y_dim="latitude",
    )
    cnv.layout(((surface_ref,),))
    app = _lower(source)

    view = next(
        candidate
        for candidate in app.view_catalog.views.values()
        if isinstance(candidate, ViewSpec) and candidate.kind == "surface"
    )
    field_spec = app.data.fields[view.inputs["field"]]

    assert not app.data.geometries
    assert "geometry_id" not in view.properties
    assert not hasattr(surface_ref, "geometry_id")
    assert field_spec.dims == ("latitude", "longitude")
    np.testing.assert_array_equal(field_spec.coords["longitude"], x)
    np.testing.assert_array_equal(field_spec.coords["latitude"], y)

    scene = surface_scene_from_field(field_spec.materialize())
    np.testing.assert_array_equal(scene.x_grid[0], x)
    np.testing.assert_array_equal(scene.y_grid[:, 0], y)
    np.testing.assert_array_equal(scene.z, values)

    # T2 matrix regression: field-owned coordinates survive the exact serializer
    # used by multiprocessing.Pipe without requiring an OS pipe in the unit test.
    transported_app = ForkingPickler.loads(ForkingPickler.dumps(app))
    transported_view = next(
        candidate
        for candidate in transported_app.view_catalog.views.values()
        if isinstance(candidate, ViewSpec) and candidate.kind == "surface"
    )
    transported_field = transported_app.data.fields[transported_view.inputs["field"]]
    assert transported_field.dims == ("latitude", "longitude")
    np.testing.assert_array_equal(transported_field.coords["longitude"], x)
    np.testing.assert_array_equal(transported_field.coords["latitude"], y)


def test_context_set_data_replaces_one_static_surface_snapshot():
    from compneurovis.core.messages import FieldReplace

    inline._reset_authoring_app()
    source = cnv.source()
    surface = source.surface(
        "Explicit snapshot",
        values=np.zeros((2, 3), dtype=np.float32),
        x=np.arange(3, dtype=np.float32),
        y=np.arange(2, dtype=np.float32),
    )
    cnv.layout(((surface,),))
    source._panel_grid = inline._current_authoring_app()._panel_grid
    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    backend.initialize(app_spec)
    backend.take_outbound_messages()

    backend.tick()
    assert not backend.take_outbound_messages()

    updated = np.full((2, 3), 7.0, dtype=np.float32)
    backend._interaction_context().set_data(surface, updated)
    replacements = [
        message.payload
        for message in backend.take_outbound_messages()
        if isinstance(message.payload, FieldReplace)
    ]
    assert len(replacements) == 1
    np.testing.assert_array_equal(replacements[0].values, updated)

    backend.tick()
    assert not backend.take_outbound_messages()

    backend.reset_field_history({surface.field_id})
    reset = backend.take_outbound_messages()[-1].payload
    np.testing.assert_array_equal(reset.values, updated)


def test_morphology_geometry_is_widget_owned_and_app_spec_neutral():
    from multiprocessing.reduction import ForkingPickler

    from compneurovis.geometries.morphology import (
        morphology_geometry_from_spec,
    )

    inline._reset_authoring_app()
    geometry = cnv.MorphologyGeometry(
        id="cable",
        positions=np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
        orientations=np.asarray([np.eye(3)], dtype=np.float32),
        radii=np.asarray([1.0], dtype=np.float32),
        lengths=np.asarray([2.0], dtype=np.float32),
        entity_ids=("soma",),
        section_names=("soma",),
        xlocs=np.asarray([0.5], dtype=np.float32),
    )
    source = cnv.source()
    morphology = source.morphology(
        geometry,
        values=np.asarray([-65.0], dtype=np.float32),
        selected="soma",
    )
    cnv.layout(((morphology,),))
    app = _lower(source)

    spec = next(iter(app.data.geometries.values()))
    view = next(
        candidate
        for candidate in app.view_catalog.views.values()
        if isinstance(candidate, ViewSpec)
        and candidate.kind == "morphology"
    )
    assert isinstance(spec, GeometrySpec)
    assert spec.kind == "morphology"
    assert view.geometries["morphology"] == spec.id
    assert morphology.selected.id in app.interactions.selections

    transported = ForkingPickler.loads(ForkingPickler.dumps(app))
    transported_spec = next(iter(transported.data.geometries.values()))
    reconstructed = morphology_geometry_from_spec(transported_spec)
    assert reconstructed is not None
    assert reconstructed.entity_info("soma")["xloc"] == pytest.approx(0.5)


def test_morphology_geometry_builds_entity_metadata_without_per_entity_lookup(
    monkeypatch,
):
    from compneurovis.core.geometry import geometry_entity_info

    geometry = cnv.MorphologyGeometry(
        id="cable",
        positions=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        orientations=np.asarray([np.eye(3), np.eye(3)], dtype=np.float32),
        radii=np.asarray([1.0, 0.5], dtype=np.float32),
        lengths=np.asarray([2.0, 1.0], dtype=np.float32),
        entity_ids=("soma", "axon"),
        section_names=("cell.soma", "cell.axon"),
        xlocs=np.asarray([0.5, 0.25], dtype=np.float32),
        labels=("Soma", "Axon"),
    )

    def fail_repeated_lookup(*_args, **_kwargs):
        raise AssertionError("to_spec must not scan entity_ids once per entity")

    monkeypatch.setattr(cnv.MorphologyGeometry, "entity_info", fail_repeated_lookup)
    spec = geometry.to_spec()

    assert spec.metadata["entity_fields"] == {
        "position": "positions",
        "orientation": "orientations",
        "radius": "radii",
        "length": "lengths",
        "section_name": "section_names",
        "xloc": "xlocs",
        "label": "labels",
    }
    assert "entities" not in spec.metadata
    info = geometry_entity_info(spec, "soma")
    assert info is not None
    assert info["index"] == 0
    assert info["position"] == (0.0, 0.0, 0.0)
    assert info["orientation"] == (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    assert info["radius"] == pytest.approx(1.0)
    assert info["length"] == pytest.approx(2.0)
    assert info["section_name"] == "cell.soma"
    assert info["xloc"] == pytest.approx(0.5)
    assert info["label"] == "Soma"


def test_geometry_spec_exposes_generic_entity_metadata():
    from compneurovis.core.geometry import GeometryEntityLookup, geometry_entity_info

    spec = cnv.GeometrySpec(
        id="cloud",
        kind="third_party_points",
        data={
            "entity_ids": ("p0", "p1"),
            "labels": ("First", "Second"),
            "scores": np.asarray([0.25, 0.75], dtype=np.float32),
            "positions": np.zeros((2, 3), dtype=np.float32),
        },
        metadata={
            "entity_fields": {"label": "labels", "score": "scores"},
            "entities": {"p1": {"group": "target"}},
        },
    )

    info = geometry_entity_info(spec, "p1")
    assert info["index"] == 1
    assert info["labels"] == "Second"
    assert info["scores"] == pytest.approx(0.75)
    assert info["label"] == "Second"
    assert info["score"] == pytest.approx(0.75)
    assert info["group"] == "target"
    assert "positions" not in info
    assert geometry_entity_info(spec, "missing") is None

    other = cnv.GeometrySpec(
        id="other-cloud",
        kind="third_party_points",
        data={"entity_ids": ("p1",)},
        metadata={"entities": {"p1": {"group": "other"}}},
    )
    lookup = GeometryEntityLookup((spec, other))
    assert lookup.entity_info("p1", geometry_id="cloud")["group"] == "target"
    assert lookup.entity_info("p1", geometry_id="other-cloud")["group"] == "other"


def test_bound_level_marker_lowers_to_a_refreshable_plot_contribution():
    from compneurovis.core import ValueBindingSpec
    from compneurovis.frontends.vispy.refresh_planning import _contains_binding

    properties = {"value": ValueBindingSpec(key="threshold")}
    assert _contains_binding(properties, "threshold", "root")
    assert not _contains_binding(properties, "unrelated", "root")

    inline._reset_authoring_app()
    source = cnv.source()
    threshold = source.slider(
        "threshold", label="Threshold", min=-1.0, max=1.0, default=0.0
    )
    line = source.line(
        "Signal",
        source=cnv.widgets.DataRef(_field_id="missing"),
    )
    marker_target = source.level_marker(line, threshold, color="red")
    assert marker_target is line
    contributions = tuple(
        item.contribution()
        for item in source._widgets
    )
    marker_contribution = next(
        item for item in contributions if item.visual_contributions
    )
    marker = marker_contribution.visual_contributions[0]
    assert marker.kind == "level_marker"
    assert marker.capability == "plot2d.layers/v1"
    assert marker.properties["value"] == ValueBindingSpec(threshold.value_key)
    assert marker_contribution.panel_contribution_ids[line.id] == (marker.id,)


def test_register_widget_names_a_source_method():
    """A registered widget gets ``source.<name>(...)`` -- the opt-in named surface
    the built-ins have, available to any (third-party) widget."""
    inline._reset_authoring_app()
    from compneurovis import register_widget, registered_widgets
    from compneurovis.inline.widgets.api import Widget
    from compneurovis.inline.widget_registry import _widget_factories

    calls = []

    class Probe(Widget):
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs

        def declare(self, context):
            calls.append((self.args, self.kwargs))
            return "PROBE_REF"

    try:
        register_widget("probe", Probe)
        assert "probe" in registered_widgets()
        source = cnv.source()
        # discoverable despite dynamic dispatch
        assert "probe" in dir(source)
        # source.probe(...) == source.add(Probe(...)); args forwarded, ref returned
        ref = source.probe(1, x=2)
        assert ref == "PROBE_REF"
        assert calls == [((1,), {"x": 2})]
        # cannot shadow a built-in source method
        with pytest.raises(ValueError, match="built-in"):
            register_widget("add", Probe)
        # unknown attributes still raise AttributeError (dispatch doesn't mask them)
        with pytest.raises(AttributeError):
            source.definitely_not_registered
    finally:
        _widget_factories.pop("probe", None)


def test_first_party_authoring_uses_the_public_registries_idempotently():
    from compneurovis.components.line.authoring import Line
    from compneurovis.inline.builtin_actions import button
    from compneurovis.inline.builtin_controls import slider

    assert {
        "line",
        "bar",
        "network2d",
        "morphology",
        "surface",
        "grid_slice",
        "level_marker",
    } <= set(cnv.registered_widgets())

    # Typed methods and public diagnostics share these exact factories. Repeating
    # the owning registration is a no-op even after source methods are reserved.
    cnv.register_widget("line", Line)
    cnv.register_control("slider", slider, override=True)
    cnv.register_action("button", button, override=True)


def test_neuron_source_builds_morphology_and_selection_trace():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    inline._reset_authoring_app()
    h("forall delete_section()")
    try:
        soma = h.Section(name="compneurovis_imported_cell.soma[0]")
        soma.L = soma.diam = 20.0
        soma.insert("hh")
        selected_soma = f"{soma.name()}@0.50000"
        public_selected_soma = "soma[0]@0.50000"

        source = cnv.neuron.source(
            sections=[soma],
            dt=0.025,
            display_dt=0.5,
        )
        morphology = source.morphology(
            variable="v",
            selected=selected_soma,
        )
        voltage_data = source.record_selection(
            "Selected voltage",
            selection=morphology.selection,
            variables={"Voltage": "v"},
        )
        voltage = source.line("Selected voltage", source=voltage_data)
        direct_voltage = source.line(
            "Direct selected voltage",
            source=morphology.selection,
            rolling_window=120.0,
        )
        cnv.layout(((morphology, voltage, direct_voltage),))

        source._panel_grid = inline._current_authoring_app()._panel_grid
        backend = source._make_backend()
        app_spec = source._build_app_spec_for_backend(backend)
        views = tuple(app_spec.view_catalog.views.values())
        morphology_view = next(
            view
            for view in views
            if isinstance(view, ViewSpec) and view.kind == "morphology"
        )
        assert morphology_view.selections["entities"] == morphology.selected.id
        assert morphology_view.geometries["morphology"]
        assert morphology_view.properties["camera_pan_sensitivity"] == 100.0
        assert morphology_view.properties["camera_zoom_sensitivity"] == 1.2
        assert morphology.selected.id in app_spec.interactions.selections
        assert "_selected" not in app_spec.interactions.selections
        assert any(
            isinstance(view, ViewSpec) and view.kind == "line_plot"
            for view in views
        )
        history_field = app_spec.data.fields[morphology.selection._field_id]
        assert history_field.retention
        assert history_field.retention[0].min_duration == 120.0
        from compneurovis.core.messages import (
            FieldReplace,
            ValueChange,
            command_message,
        )

        backend.initialize(app_spec)
        histories = {
            binding._field_id: binding
            for binding in backend._segment_variable_histories
        }
        assert histories[morphology.selection._field_id].max_samples >= 4801
        assert histories[voltage_data._field_id].max_samples >= 20001
        initial_updates = backend.take_outbound_messages()
        direct_history_replace = next(
            message.payload
            for message in initial_updates
            if isinstance(message.payload, FieldReplace)
            and message.payload.field_id == morphology.selection._field_id
        )
        assert direct_history_replace.values.shape == (1, 1)
        assert direct_history_replace.coords["segment"].tolist() == [
            public_selected_soma
        ]
        assert backend.values.get(morphology.selected.id) == [public_selected_soma]
        backend.handle(
            command_message(
                clicked(morphology.entity_click.id, public_selected_soma)
            )
        )
        assert backend.values.get(morphology.selected.id) == [public_selected_soma]
        selection_updates = [
            message.payload
            for message in backend.take_outbound_messages()
            if isinstance(message.payload, ValueChange)
        ]
        assert selection_updates == []
    finally:
        h("forall delete_section()")


def test_neuron_morphology_widgets_own_fields_and_selections_independently():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    from compneurovis.core.messages import (
        FieldAppend,
        FieldReplace,
        command_message,
    )

    inline._reset_authoring_app()
    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        soma.L = soma.diam = 20.0
        soma.insert("hh")

        source = cnv.neuron.source(
            sections=[soma],
            dt=0.025,
            display_dt=0.05,
        )
        voltage = source.morphology(
            variable="v",
            name="Voltage",
            selected="soma@0.50000",
        )
        activation = source.morphology(
            variable="m_hh",
            name="Activation",
        )
        fixed = source.record(
            "Fixed voltage",
            sample=lambda: (float(soma.v),),
            series=("soma",),
        )
        cnv.layout(((voltage, activation),))

        source._panel_grid = inline._current_authoring_app()._panel_grid
        backend = source._make_backend()
        app_spec = source._build_app_spec_for_backend(backend)
        morphology_views = [
            view
            for view in app_spec.view_catalog.views.values()
            if isinstance(view, ViewSpec) and view.kind == "morphology"
        ]

        assert len(morphology_views) == 2
        assert morphology_views[0].inputs["color"] != morphology_views[1].inputs["color"]
        assert voltage.selection._field_id != activation.selection._field_id
        assert voltage.selected.id != activation.selected.id

        backend.initialize(app_spec)
        backend.take_outbound_messages()
        assert backend.values.get(voltage.selected.id) == ["soma@0.50000"]
        assert backend.values.get(activation.selected.id) == []

        backend.handle(
            command_message(
                clicked(activation.entity_click.id, "soma@0.50000")
            )
        )
        assert backend.values.get(voltage.selected.id) == ["soma@0.50000"]
        assert backend.values.get(activation.selected.id) == ["soma@0.50000"]
        replacements = {
            message.payload.field_id
            for message in backend.take_outbound_messages()
            if isinstance(message.payload, FieldReplace)
        }
        assert voltage.selection._field_id not in replacements
        assert activation.selection._field_id in replacements
        assert fixed._field_id not in replacements

        backend.tick()
        appended = {
            message.payload.field_id
            for message in backend.take_outbound_messages()
            if isinstance(message.payload, FieldAppend)
        }
        assert voltage.selection._field_id in appended
        assert activation.selection._field_id in appended
    finally:
        h("forall delete_section()")


def test_neuron_morphology_display_is_atomically_retargetable():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    from compneurovis.core.messages import (
        FieldReplace,
    )

    inline._reset_authoring_app()
    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        soma.insert("hh")
        source = cnv.neuron.source(sections=[soma], dt=0.025)
        morphology = source.morphology(
            name="Dynamic morphology",
            variable="v",
            unit="mV",
            color_limits=(-80.0, 50.0),
            selected="soma@0.50000",
        )
        cnv.layout(((morphology,),))

        source._panel_grid = inline._current_authoring_app()._panel_grid
        backend = source._make_backend()
        app_spec = source._build_app_spec_for_backend(backend)
        morphology_view = next(
            view
            for view in app_spec.view_catalog.views.values()
            if isinstance(view, ViewSpec) and view.kind == "morphology"
        )
        display_field_id = morphology_view.inputs["color"]

        backend.initialize(app_spec)
        backend.take_outbound_messages()
        # A retarget commits in the call that requests it: the display and its
        # dependent history are republished together, never left half-updated
        # waiting on the step loop.
        morphology.set_display(
            name="activation",
            data="m_hh",
            color_limits=(0.0, 1.0),
            color_map="ramp:#0000ff:#ff0000",
        )
        replacements = [
            message.payload
            for message in backend.take_outbound_messages()
            if isinstance(message.payload, FieldReplace)
        ]

        assert any(item.field_id == display_field_id for item in replacements)
        history = next(
            item
            for item in replacements
            if item.field_id == morphology.selection._field_id
        )
        assert history.attrs_update["variable"] == "activation"
        display = next(
            item for item in replacements if item.field_id == display_field_id
        )
        assert display.attrs_update["color_limits"] == (0.0, 1.0)
        assert display.attrs_update["color_map"] == "ramp:#0000ff:#ff0000"

        morphology.set_display(
            name="voltage",
            data="v",
            unit="mV",
            color_limits=(-80.0, 50.0),
            color_map="scalar",
        )
        cached_replacements = [
            message.payload
            for message in backend.take_outbound_messages()
            if isinstance(message.payload, FieldReplace)
        ]
        assert any(
            item.field_id == display_field_id for item in cached_replacements
        )
        # Returning to a previously displayed source reuses its proven reader.
        # Readers are owned by the backend, not the display binding, so
        # returning to a previously shown source reuses its compiled reader.
        assert backend.segment_readers.is_prepared("v")
        assert backend.segment_readers.is_prepared("m_hh")
    finally:
        h("forall delete_section()")


def test_neuron_scalar_callable_display_source_falls_back_to_sampled_reads():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from types import SimpleNamespace

    from neuron import h

    from compneurovis.backends.neuron.segment_readers import SegmentValueReaders

    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        soma.Ra = 87.0
        backend = SimpleNamespace(
            geometry=SimpleNamespace(
                entity_ids=("soma@0.50000",),
                section_names=("soma",),
                xlocs=(0.5,),
            ),
            sections_by_name=lambda: {"soma": soma},
        )
        readers = SegmentValueReaders()
        source = lambda segment: float(segment.sec.Ra)

        # A callable returning a plain value has no pointer to compile, so it
        # is recorded as non-native and read segment by segment instead.
        assert readers.prepare(backend, source) is False
        assert readers.read(backend, source).tolist() == pytest.approx([87.0])
    finally:
        h("forall delete_section()")


def test_neuron_morphology_display_accepts_mutable_explicit_segment_values():
    from types import SimpleNamespace

    from compneurovis.backends.neuron.segment_readers import SegmentValueReaders
    from compneurovis.backends.neuron.source.recording import (
        SegmentVariableDisplayBinding,
    )

    backend = SimpleNamespace(
        geometry=SimpleNamespace(entity_ids=("first", "second")),
        segment_readers=SegmentValueReaders(),
    )
    values = np.asarray([35.4, 70.0], dtype=np.float32)
    binding = SegmentVariableDisplayBinding(
        name="Axial resistance",
        variable="Ra",
        source=values,
    )

    assert binding._read_values(backend).tolist() == pytest.approx([35.4, 70.0])
    values[0] = 90.0
    assert binding._read_values(backend).tolist() == pytest.approx([90.0, 70.0])


def test_neuron_segment_readers_are_backend_owned_and_prepared_at_startup():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    inline._reset_authoring_app()
    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        soma.insert("hh")
        source = cnv.neuron.source(sections=[soma], dt=0.025)
        # Declared before any morphology exists, and never displayed by one.
        source.prepare_segment_values("m_hh", "gkbar_hh")
        first = source.morphology(name="First", variable="v", selectable=False)
        second = source.morphology(name="Second", variable="v", selectable=False)
        cnv.layout(((first,), (second,)))

        source._panel_grid = inline._current_authoring_app()._panel_grid
        backend = source._make_backend()
        backend.initialize(source._build_app_spec_for_backend(backend))

        # Prepared without a view asking for them.
        assert backend.segment_readers.is_prepared("m_hh")
        assert backend.segment_readers.is_prepared("gkbar_hh")
        # Two morphologies over one geometry share a single compiled reader.
        assert first._display._binding is not second._display._binding
        assert backend.segment_readers.is_prepared("v")
        assert len(backend.segment_readers._readers) == 3
    finally:
        h("forall delete_section()")


def test_neuron_history_following_a_display_declares_no_variables():
    from compneurovis.backends.neuron.source.recording import (
        SegmentVariableDisplayBinding,
        SegmentVariableHistoryBinding,
    )

    display = SegmentVariableDisplayBinding(
        name="Display", variable="v", source="v", unit="mV"
    )

    # A follower takes its quantity and unit from the display.
    follower = SegmentVariableHistoryBinding(
        name="trace",
        selection_id="sel",
        display_binding=display,
        include_variable_dim=False,
    )
    assert follower._active_variables() == (("v", "v"),)

    # Declaring both would leave a second, silently ignored source of truth.
    with pytest.raises(ValueError, match="must not also declare variables"):
        SegmentVariableHistoryBinding(
            name="trace",
            selection_id="sel",
            variables={"v": "v"},
            display_binding=display,
            include_variable_dim=False,
        )

    # A standalone history still requires its own variables.
    with pytest.raises(ValueError, match="at least one variable"):
        SegmentVariableHistoryBinding(name="trace", selection_id="sel")


def test_neuron_retargetable_field_unit_lives_only_in_attrs():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    inline._reset_authoring_app()
    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        soma.insert("hh")
        source = cnv.neuron.source(sections=[soma], dt=0.025)
        morphology = source.morphology(
            name="Morph", variable="v", unit="mV", selected="soma@0.50000"
        )
        cnv.layout(((morphology,),))
        source._panel_grid = inline._current_authoring_app()._panel_grid
        backend = source._make_backend()
        backend.initialize(source._build_app_spec_for_backend(backend))

        display = morphology._display._binding
        field = display._initial_field(backend)
        # FieldReplace cannot carry unit, so the retargetable copy is in attrs
        # only -- a FieldSpec.unit here would strand a stale value.
        assert field.unit is None
        assert field.attrs["unit"] == "mV"

        morphology.set_display(name="activation", data="m_hh", unit=None)
        assert display._replace_payload(backend).attrs_update["unit"] == ""
    finally:
        h("forall delete_section()")


def test_neuron_derived_segment_values_read_in_bulk_and_per_segment():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    from compneurovis.backends.neuron.segment_readers import (
        SegmentValueReaders,
        as_producer,
    )

    inline._reset_authoring_app()
    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        soma.insert("hh")
        soma.nseg = 3
        soma.cm = 1.5
        source = cnv.neuron.source(sections=[soma], dt=0.025)
        combined = source.derived_segment_values(
            "v", "cm", fn=lambda v, cm: 2.0 * v + cm, name="2Vm+Cm"
        )
        source.prepare_segment_values(combined)
        morphology = source.morphology(
            name="Derived", variable=combined, selected="soma@0.50000"
        )
        cnv.layout(((morphology,),))

        source._panel_grid = inline._current_authoring_app()._panel_grid
        backend = source._make_backend()
        backend.initialize(source._build_app_spec_for_backend(backend))

        # Preparing the derived quantity compiled each input's reader.
        assert backend.segment_readers.is_prepared("v")
        assert backend.segment_readers.is_prepared("cm")
        assert backend.segment_readers.is_prepared(combined)

        expected = 2.0 * float(soma(0.5).v) + 1.5
        bulk = backend.segment_readers.read(backend, combined)
        assert len(bulk) == len(backend.geometry.entity_ids)
        assert bulk.tolist() == pytest.approx([expected] * len(bulk))

        # The same function answers one segment for a selection trace.
        readers = SegmentValueReaders()
        per_segment = as_producer(combined).sample(backend, readers, soma(0.5), 0)
        assert per_segment == pytest.approx(expected)
    finally:
        h("forall delete_section()")


def test_neuron_segment_value_producer_needs_only_conformance():
    from types import SimpleNamespace

    import numpy as np

    from compneurovis.backends.neuron.segment_readers import (
        SegmentValueProducer,
        SegmentValueReaders,
        as_producer,
    )

    class ThirdPartyValues:
        """A producer defined outside the library, registered by conforming."""

        def describe(self):
            return "third-party"

        def is_prepared(self, readers):
            return True

        def prepare(self, backend, readers):
            return True

        def read(self, backend, readers):
            return np.arange(
                len(backend.geometry.entity_ids), dtype=np.float32
            )

        def sample(self, backend, readers, seg, index):
            return float(index)

    backend = SimpleNamespace(
        geometry=SimpleNamespace(entity_ids=("a", "b", "c")),
        segment_readers=SegmentValueReaders(),
    )
    produced = ThirdPartyValues()

    assert isinstance(produced, SegmentValueProducer)
    # as_producer passes it through untouched -- no arm was added for it.
    assert as_producer(produced) is produced
    assert backend.segment_readers.read(backend, produced).tolist() == [0.0, 1.0, 2.0]
    assert backend.segment_readers.is_prepared(produced)

    # And it composes into a derived quantity like any built-in source.
    from compneurovis.backends.neuron.segment_readers import DerivedSegmentValues

    doubled = DerivedSegmentValues(
        inputs=(produced,), fn=lambda values: values * 2.0, name="doubled"
    )
    assert backend.segment_readers.read(backend, doubled).tolist() == [0.0, 2.0, 4.0]
    assert doubled.sample(backend, backend.segment_readers, None, 2) == 4.0
    assert doubled.describe() == "doubled(third-party)"


def test_neuron_nonselectable_morphology_has_no_selection_history_producer():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    inline._reset_authoring_app()
    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        source = cnv.neuron.source(sections=[soma])
        morphology = source.morphology(variable="v", selectable=False)

        assert morphology.selection is None
        assert source._segment_variable_histories == []
    finally:
        h("forall delete_section()")


def test_low_level_neuron_backend_runs_without_a_display_sampler():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    from compneurovis.backends.neuron.backend import NeuronBackend
    from compneurovis.core.messages import Reset, command_message

    captured: list[tuple[np.ndarray, dict[str, np.ndarray]]] = []

    class RecordingBackend(NeuronBackend):
        def build_sections(self):
            return [h.Section(name="recording_soma")]

        def setup_model(self, sections):
            self.record("voltage", sections[0](0.5)._ref_v)

        def on_recorded_samples(self, times, values):
            captured.append((times, values))

    h("forall delete_section()")
    try:
        backend = RecordingBackend(dt=0.025, display_dt=0.025)
        startup = backend.build_startup_data()
        assert startup.fields == ()
        assert startup.geometries == ()
        assert backend._recorded_names == ["voltage"]

        backend.initialize(AppSpec())
        backend.tick()
        assert len(captured) == 1
        assert captured[0][0].shape == (1,)
        assert captured[0][1]["voltage"].shape == (1,)

        backend.handle(command_message(Reset()))
        assert backend._last_time_value == pytest.approx(0.0)
    finally:
        h("forall delete_section()")


def test_jaxley_namespace_imports_when_installed():
    if find_spec("jaxley") is None:
        pytest.skip("Jaxley extra is not installed")

    assert callable(cnv.jaxley.source)


def test_jaxley_morphology_uses_generic_component_declaration():
    from compneurovis.backends.jaxley.source.declarations import JaxleyInlineSource

    source = JaxleyInlineSource()
    morphology = source.morphology(selected="cell_0:branch_0@0.50000")
    views = [
        view
        for binding in source._bindings_for_compose()
        for view in getattr(binding, "views", ())
    ]
    view = next(view for view in views if view.kind == "morphology")

    assert morphology.id == "morphology-panel"
    assert view.inputs["color"] == source.DISPLAY_FIELD_ID
    assert view.properties["camera_pan_sensitivity"] == 100.0
    assert view.properties["camera_zoom_sensitivity"] == 1.2


def test_jaxley_backend_routes_each_geometry_selection_independently():
    from types import SimpleNamespace

    from compneurovis.backends.jaxley.backend import JaxleyBackend
    from compneurovis.core import (
        DataCatalog,
        ClickSpec,
        HitTargetSpec,
        InteractionCatalog,
        SelectionSpec,
    )
    from compneurovis.core.messages import (
        ValueChange,
        command_message,
    )

    class SelectionBackend(JaxleyBackend):
        def build_cells(self):
            return ()

    geometry_spec = GeometrySpec(
        id="morphology",
        kind="morphology",
        data={"entity_ids": ("a", "b")},
    )
    single = SelectionSpec(
        id="single",
        target_id=geometry_spec.id,
        initial=("a",),
    )
    multiple = SelectionSpec(
        id="multiple",
        target_id=geometry_spec.id,
        initial=("b",),
        multiple=True,
    )
    target = HitTargetSpec(id="morphology_hit")
    single_click = ClickSpec(
        id="single_click",
        hit_target_id=target.id,
        result_kind="entity",
        geometry_scope_id=geometry_spec.id,
        selection_id=single.id,
    )
    multiple_click = ClickSpec(
        id="multiple_click",
        hit_target_id=target.id,
        result_kind="entity",
        geometry_scope_id=geometry_spec.id,
        selection_id=multiple.id,
    )
    app_spec = AppSpec(
        data=DataCatalog(
            geometries={geometry_spec.id: geometry_spec},
        ),
        interactions=InteractionCatalog(
            selections={single.id: single, multiple.id: multiple},
            hit_targets={target.id: target},
            clicks={
                single_click.id: single_click,
                multiple_click.id: multiple_click,
            },
        ),
    )
    backend = SelectionBackend()
    backend.geometry = SimpleNamespace(
        id=geometry_spec.id,
        entity_ids=("a", "b"),
    )
    backend._entity_index_by_id = {"a": 0, "b": 1}

    backend.initialize(app_spec)
    assert backend.values.get(single.id) == ["a"]
    assert backend.values.get(multiple.id) == ["b"]
    assert backend.selection_id() is None
    assert backend._preferred_series_entity_ids() == ["a", "b"]

    backend.handle(command_message(clicked(multiple_click.id, "a")))
    assert backend.values.get(single.id) == ["a"]
    assert backend.values.get(multiple.id) == ["b", "a"]
    assert backend.selection_id() is None

    backend.handle(command_message(clicked(single_click.id, "b")))
    assert backend.values.get(single.id) == ["b"]
    assert backend.values.get(multiple.id) == ["b", "a"]
    assert backend.selection_id() is None

    backend.handle(command_message(clicked("unknown", "a")))
    assert backend.selection_id() is None

    backend.handle(command_message(ValueChange({"unbound": 3})))
    assert backend.values.get("unbound") == 3
    assert not hasattr(backend, "unbound")


def test_entity_clicks_are_independent_from_optional_selection_policy():
    from compneurovis.backends import BackendBase
    from compneurovis.core import (
        AppSpec,
        DataCatalog,
        ClickSpec,
        GeometrySpec,
        HitTargetSpec,
        InteractionCatalog,
        SelectionSpec,
    )
    from compneurovis.core.messages import command_message

    geometry = GeometrySpec(
        id="morphology",
        kind="morphology",
        data={"entity_ids": ("soma", "dendrite")},
        metadata={
            "entities": {
                "soma": {"kind": "soma"},
                "dendrite": {"kind": "dendrite"},
            }
        },
    )
    inspection_geometry = GeometrySpec(
        id="inspection_overlay",
        kind="morphology",
        data={"entity_ids": ("dendrite",)},
        metadata={"entities": {"dendrite": {"kind": "inspection"}}},
    )
    selection = SelectionSpec(
        id="selected",
        target_id=geometry.id,
        initial=("soma",),
    )
    morphology_target = HitTargetSpec(
        id="morphology_hit",
    )
    inspection_target = HitTargetSpec(
        id="inspection_hit",
    )
    select_click = ClickSpec(
        id="select_click",
        hit_target_id=morphology_target.id,
        result_kind="entity",
        geometry_scope_id=geometry.id,
        selection_id=selection.id,
    )
    editor_click = ClickSpec(
        id="editor_click",
        hit_target_id=morphology_target.id,
        result_kind="entity",
        geometry_scope_id=geometry.id,
        selection_id=selection.id,
    )
    inspect_click = ClickSpec(
        id="inspect_click",
        hit_target_id=inspection_target.id,
        result_kind="entity",
        geometry_scope_id=inspection_geometry.id,
    )
    app_spec = AppSpec(
        data=DataCatalog(
            geometries={
                geometry.id: geometry,
                inspection_geometry.id: inspection_geometry,
            }
        ),
        interactions=InteractionCatalog(
            selections={selection.id: selection},
            hit_targets={
                morphology_target.id: morphology_target,
                inspection_target.id: inspection_target,
            },
            clicks={
                select_click.id: select_click,
                editor_click.id: editor_click,
                inspect_click.id: inspect_click,
            },
        ),
    )

    class EditorBackend(BackendBase):
        def __init__(self):
            super().__init__()
            self.clicks = []

        def intercept_click(self, event, context) -> bool:
            interaction_id = event.interaction_id
            entity_id = event.value
            self.clicks.append(
                (
                    interaction_id,
                    entity_id,
                    context.entity_click_id,
                    context.entity_info(entity_id)["kind"],
                )
            )
            return interaction_id == editor_click.id

    backend = EditorBackend()
    backend.initialize(app_spec)
    backend.take_outbound_messages()

    # The editor consumes a click whose spec has a selection link; selection is
    # still untouched because coupling applies only to an unconsumed click.
    backend.handle(command_message(clicked(editor_click.id, "dendrite")))
    assert backend.values.get(selection.id) == ["soma"]

    # A pure click has geometry/context but no selection behavior at all.
    backend.handle(command_message(clicked(inspect_click.id, "dendrite")))
    assert backend.values.get(selection.id) == ["soma"]

    # This widget interaction explicitly opts into the shared selection policy.
    backend.handle(command_message(clicked(select_click.id, "dendrite")))
    assert backend.values.get(selection.id) == ["dendrite"]
    assert backend.clicks == [
        ("editor_click", "dendrite", "editor_click", "dendrite"),
        ("inspect_click", "dendrite", "inspect_click", "inspection"),
        ("select_click", "dendrite", "select_click", "dendrite"),
    ]


def test_multiple_controls_widgets_own_their_controls_independently():
    from multiprocessing.reduction import ForkingPickler

    inline._reset_authoring_app()
    source = cnv.source()

    simulation = source.controls("Simulation")
    speed = simulation.slider(
        "speed", label="Speed", min=0.0, max=2.0, default=1.0
    )
    display = source.controls("Display")
    palette = display.dropdown(
        "palette", label="Palette", options=("warm", "cool"), default="warm"
    )
    display.button("reset_display", label="Reset display", fn=lambda ctx: None)

    cnv.layout(((simulation, display),))
    app_spec = _lower(source)
    layout = app_spec.layout_catalog.active_layout()
    simulation_panel = layout.panel(simulation.id)
    display_panel = layout.panel(display.id)

    assert simulation_panel is not None
    assert display_panel is not None
    assert simulation_panel.control_ids == (speed.value_key,)
    assert display_panel.control_ids == (palette.value_key,)
    assert len(display_panel.action_ids) == 1
    assert not set(simulation_panel.control_ids) & set(display_panel.control_ids)
    assert layout.panel("controls-panel") is None
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner

    planner = RefreshPlanner(app_spec, lambda: layout)
    assert {
        target.panel_id
        for target in planner.targets_for_control_value(speed.value_key)
        if target.kind == "controls"
    } == {simulation.id}
    assert {
        target.panel_id
        for target in planner.targets_for_control_patch(palette.value_key)
    } == {display.id}
    assert ForkingPickler.dumps(app_spec)


def test_button_and_hotkey_compose_one_action_in_either_order():
    from compneurovis.inline.refs import ButtonRef, HotkeyRef

    inline._reset_authoring_app()
    source = cnv.source()
    controls = source.controls("Actions")
    calls: list[str] = []

    space = controls.hotkey("Space", fn=lambda ctx: calls.append("space"))
    play = controls.button("play", label="Play", hotkey=space)
    reset = controls.button(
        "reset",
        label="Reset",
        fn=lambda ctx: calls.append("reset"),
    )
    reused_reset = controls.hotkey("R", reset)

    assert isinstance(space, HotkeyRef)
    assert isinstance(play, ButtonRef)
    assert play._binding is space._binding
    assert isinstance(reset, ButtonRef)
    assert reused_reset is reset

    cnv.layout(((controls,),))
    app_spec = _lower(source)
    panel = app_spec.layout_catalog.active_layout().panel(controls.id)
    assert panel is not None
    assert len(app_spec.interactions.actions) == 2
    assert panel.action_ids == (
        play._binding._action_id,
        reset._binding._action_id,
    )
    assert app_spec.action(play._binding._action_id).shortcuts == ("Space",)
    assert app_spec.action(reset._binding._action_id).shortcuts == ("R",)

    backend = source._make_backend()
    source._build_app_spec_for_backend(backend)
    assert backend._dispatch_action(play._binding._action_id, {})
    assert backend._dispatch_action(reset._binding._action_id, {})
    assert calls == ["space", "reset"]


def test_button_hotkey_composition_rejects_ambiguous_or_wrong_refs():
    inline._reset_authoring_app()
    source = cnv.source()
    controls = source.controls("Actions")
    space = controls.hotkey("Space", fn=lambda ctx: None)
    button = controls.button("button", label="Button", fn=lambda ctx: None)

    with pytest.raises(ValueError, match="reuses its callback"):
        controls.button(
            "ambiguous",
            label="Ambiguous",
            fn=lambda ctx: None,
            hotkey=space,
        )
    with pytest.raises(TypeError, match="expects HotkeyRef"):
        controls.button("wrong", label="Wrong", hotkey=button)

    other_source = cnv.source()
    other_controls = other_source.controls("Other actions")
    with pytest.raises(ValueError, match="another source"):
        other_controls.button("cross_source", label="Cross source", hotkey=space)
    with pytest.raises(ValueError, match="another source"):
        other_controls.hotkey("X", button)


def test_backend_context_sets_control_ref_by_its_value_key():
    from compneurovis.core.messages import ValueChange

    inline._reset_authoring_app()
    source = cnv.source()
    gain = source.slider(
        "gain", label="Gain", min=0.0, max=1.0, default=0.25
    )
    source.button(
        "set_gain",
        label="Set gain",
        fn=lambda ctx: ctx.set_value(gain, 0.75),
    )
    cnv.layout(((source.controls_panel,),))

    source._panel_grid = inline._current_authoring_app()._panel_grid
    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    backend.initialize(app_spec)
    backend.take_outbound_messages()

    action_id = next(iter(app_spec.interactions.actions))
    assert backend._dispatch_action(action_id, {})
    updates = [
        message.payload
        for message in backend.take_outbound_messages()
        if isinstance(message.payload, ValueChange)
    ]

    assert backend.values.get(gain.value_key) == 0.75
    assert updates[-1].updates == {gain.value_key: 0.75}


def test_control_owns_mutable_runtime_visibility():
    from compneurovis.core.messages import ControlPatch

    inline._reset_authoring_app()
    source = cnv.source()
    advanced = source.slider(
        "advanced gain",
        label="Advanced gain",
        min=0.0,
        max=1.0,
        visible=False,
    )
    cnv.layout(((source.controls_panel,),))

    source._panel_grid = inline._current_authoring_app()._panel_grid
    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    backend.initialize(app_spec)
    backend.take_outbound_messages()
    control = next(iter(app_spec.interactions.controls.values()))
    assert control.visible is False

    advanced.visible = True
    updates = [
        message.payload
        for message in backend.take_outbound_messages()
        if isinstance(message.payload, ControlPatch)
    ]
    assert advanced.visible is True
    assert updates[-1] == ControlPatch(control.id, {"visible": True})


def test_controls_widget_can_select_a_third_party_panel_host_kind():
    inline._reset_authoring_app()
    source = cnv.source()
    custom = source.controls("Rack", panel_kind="third_party_control_rack")
    gain = custom.slider(
        "gain", label="Gain", min=0.0, max=1.0, default=0.5
    )
    cnv.layout(((custom,),))

    app_spec = _lower(source)
    panel = app_spec.layout_catalog.active_layout().panel(custom.id)
    assert panel.kind == "third_party_control_rack"
    assert panel.control_ids == (gain.value_key,)

    with pytest.raises(ValueError, match="already declared with kind"):
        source.controls(
            "Rack",
            panel_id=custom.id,
            panel_kind="different_control_rack",
        )


def test_registered_control_gets_source_and_controls_widget_methods():
    from multiprocessing.reduction import ForkingPickler

    from compneurovis.inline.control_registry import _control_factories

    inline._reset_authoring_app()

    def knob(
        context,
        name,
        *,
        label,
        min=0.0,
        max=1.0,
        default=0.5,
    ):
        return context.control(
            name,
            label=label,
            value_kind="scalar",
            default=float(default),
            value_properties={"min": min, "max": max},
            presentation_kind="test_knob",
            presentation_properties={"sweep_degrees": 270},
        )

    _control_factories.pop("knob", None)
    try:
        cnv.register_control("knob", knob)
        source = cnv.source()
        assert "knob" in dir(source)
        gain = source.knob("gain", label="Gain")
        advanced = source.controls("Advanced")
        bias = advanced.knob("bias", label="Bias", default=0.25)
        cnv.layout(((source.controls_panel, advanced),))

        app_spec = _lower(source)
        default_panel = app_spec.layout_catalog.active_layout().panel(
            source.controls_panel.id
        )
        advanced_panel = app_spec.layout_catalog.active_layout().panel(advanced.id)
        assert default_panel.control_ids == (gain.value_key,)
        assert advanced_panel.control_ids == (bias.value_key,)

        gain_spec = app_spec.interactions.controls[gain.value_key]
        assert gain_spec.value_spec.kind == "scalar"
        assert gain_spec.presentation.kind == "test_knob"
        assert gain_spec.presentation.property("sweep_degrees") == 270
        assert ForkingPickler.dumps(app_spec)

        with pytest.raises(ValueError, match="widget authoring name"):
            cnv.register_control("line", knob)
        with pytest.raises(ValueError, match="action authoring name"):
            cnv.register_control("button", knob)
    finally:
        _control_factories.pop("knob", None)


def test_registered_action_gets_source_and_controls_widget_methods():
    from compneurovis.inline.action_registry import _action_factories

    inline._reset_authoring_app()

    def menu_item(context, name, *, label, fn, group="default"):
        return context.action(
            name,
            label=label,
            fn=fn,
            presentation_kind="test_menu_item",
            presentation={"group": group},
        )

    def callback(ctx):
        del ctx

    _action_factories.pop("menu_item", None)
    try:
        cnv.register_action("menu_item", menu_item)
        source = cnv.source()
        assert "menu_item" in dir(source)
        primary = source.menu_item(
            "primary",
            label="Primary",
            fn=callback,
            group="main",
        )
        advanced = source.controls("Advanced")
        assert "menu_item" in dir(advanced)
        secondary = advanced.menu_item(
            "secondary",
            label="Secondary",
            fn=callback,
            group="advanced",
        )
        cnv.layout(((source.controls_panel, advanced),))

        app_spec = _lower(source)
        default_panel = app_spec.layout_catalog.active_layout().panel(
            source.controls_panel.id
        )
        advanced_panel = app_spec.layout_catalog.active_layout().panel(advanced.id)
        assert default_panel.action_ids == (primary._binding._action_id,)
        assert advanced_panel.action_ids == (secondary._binding._action_id,)
        assert (
            app_spec.action(primary._binding._action_id).presentation_kind
            == "test_menu_item"
        )
        assert (
            app_spec.action(secondary._binding._action_id).presentation["group"]
            == "advanced"
        )

        with pytest.raises(ValueError, match="authoring name"):
            cnv.register_action("slider", menu_item)
        with pytest.raises(ValueError, match="authoring name"):
            cnv.register_action("controls", menu_item)
    finally:
        _action_factories.pop("menu_item", None)


def test_entity_click_role_routes_independently_and_resolves_exact_geometry():
    from compneurovis.core.messages import command_message
    from compneurovis.inline.widgets.api import Widget

    declared = {}
    observed_owners = []

    class MultiSelectionWidget(Widget):
        def declare(self, context):
            left = context.geometry(
                "test_points",
                "left",
                data={"entity_ids": ("shared",)},
                metadata={"entities": {"shared": {"owner": "left"}}},
            )
            right = context.geometry(
                "test_points",
                "right",
                data={"entity_ids": ("shared",)},
                metadata={"entities": {"shared": {"owner": "right"}}},
            )
            left_selection = context.selection("left", geometry=left)
            right_selection = context.selection("right", geometry=right)
            left_click = context.entity_click(
                "left",
                geometry=left,
                selection=left_selection,
            )
            right_click = context.entity_click(
                "right",
                geometry=right,
                selection=right_selection,
            )
            right_inspect_click = context.entity_click(
                "right inspect",
                geometry=right,
            )
            context.on_entity_click(
                left_click,
                lambda ctx, entity_id: observed_owners.append(
                    ctx.entity_info(entity_id)["owner"]
                ),
            )
            context.on_entity_click(
                right_click,
                lambda ctx, entity_id: observed_owners.append(
                    ctx.entity_info(entity_id)["owner"]
                ),
            )
            context.on_entity_click(
                right_inspect_click,
                lambda ctx, entity_id: observed_owners.append(
                    ctx.entity_info(entity_id)["owner"]
                ),
            )
            declared.update(
                left=left_selection,
                right=right_selection,
                left_click=left_click,
                right_click=right_click,
                right_inspect_click=right_inspect_click,
            )
            return context.view(
                "multi_selection_test",
                "Selections",
                geometries={"left": left, "right": right},
                selections={
                    "left_entities": left_selection,
                    "right_entities": right_selection,
                },
                clicks={
                    "left_entities": left_click,
                    "right_entities": right_click,
                    "right_inspect": right_inspect_click,
                },
            )

    inline._reset_authoring_app()
    source = cnv.source()
    panel = source.add(MultiSelectionWidget())
    cnv.layout(((panel,),))
    app_spec = _lower(source)
    view = next(iter(app_spec.view_catalog.views.values()))
    assert view.clicks["left_entities"] == declared["left_click"].id
    assert view.clicks["right_entities"] == declared["right_click"].id
    assert view.clicks["right_inspect"] == declared["right_inspect_click"].id

    backend = source._make_backend()
    backend.initialize(app_spec)
    backend.take_outbound_messages()
    backend.handle(
        command_message(clicked(declared["right_click"].id, "shared"))
    )
    assert backend.values.get(declared["right"].id) == ["shared"]
    assert backend.values.get(declared["left"].id) == []
    assert observed_owners == ["right"]

    backend.handle(
        command_message(clicked(declared["right_inspect_click"].id, "shared"))
    )
    assert observed_owners == ["right", "right"]


def test_widget_can_target_a_panel_with_a_neutral_visual_contribution():
    from multiprocessing.reduction import ForkingPickler

    from compneurovis.inline.widgets.api import Widget

    class HaloWidget(Widget):
        def __init__(self, radius):
            self.radius = radius

        def declare(self, context):
            data = context.data("points", values=(0.0, 1.0))
            panel = context.view(
                "test_host",
                "Target",
                inputs={"data": data},
            )
            context.visual_contribution(
                "halo",
                "Selection halo",
                target=panel,
                capability="plot2d.layers/v1",
                inputs={"data": data},
                properties={"radius": self.radius, "color": "yellow"},
            )
            return panel

    inline._reset_authoring_app()
    source = cnv.source()
    radius = source.slider(
        "radius", label="Radius", min=1.0, max=10.0, default=3.0
    )
    target = source.add(HaloWidget(radius))
    cnv.layout(((target,), (source.controls_panel,)))
    app_spec = _lower(source)

    panel = app_spec.layout_catalog.active_layout().panel(target.id)
    assert len(panel.contribution_ids) == 1
    contribution_ref = panel.contribution_ids[0]
    contribution = app_spec.visual_contribution(contribution_ref)
    assert isinstance(contribution, cnv.VisualContributionSpec)
    assert contribution.kind == "halo"
    assert contribution.capability == "plot2d.layers/v1"
    assert contribution.inputs["data"] in app_spec.data.fields
    assert contribution.properties["radius"] == cnv.ValueBindingSpec(
        radius.value_key
    )
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner

    planner = RefreshPlanner(
        app_spec, lambda: app_spec.layout_catalog.active_layout()
    )
    value_targets = {
        target
        for target in planner.targets_for_value_change(radius.value_key)
        if target.kind == "visual_contribution"
    }
    assert len(value_targets) == 1
    target_refresh = value_targets.pop()
    assert target_refresh.contribution_id == cnv.app_ref(contribution_ref)
    field_targets = {
        target
        for target in planner.targets_for_field_replace(
            contribution.inputs["data"]
        )
        if target.kind == "visual_contribution"
    }
    assert {target.contribution_id for target in field_targets} == {
        cnv.app_ref(contribution_ref)
    }
    assert ForkingPickler.dumps(app_spec)


def test_visual_contribution_targets_a_viewless_panel_by_panel_id():
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner
    from compneurovis.inline.widgets.api import Widget

    class ViewlessContribution(Widget):
        def __init__(self, target, level):
            self.target = target
            self.level = level

        def declare(self, context):
            context.visual_contribution(
                "status_layer",
                "Status",
                target=self.target,
                capability="status.layers/v1",
                properties={"level": self.level},
            )
            return self.target

    inline._reset_authoring_app()
    source = cnv.source()
    target = source.controls(
        "Status host",
        panel_kind="third_party_status_host",
    )
    level = target.slider(
        "level",
        label="Level",
        min=0.0,
        max=1.0,
        default=0.5,
    )
    source.add(ViewlessContribution(target, level))
    cnv.layout(((target,),))
    app_spec = _lower(source)

    panel = app_spec.layout_catalog.active_layout().panel(target.id)
    assert panel.view_ids == ()
    assert len(panel.contribution_ids) == 1
    planner = RefreshPlanner(
        app_spec,
        lambda: app_spec.layout_catalog.active_layout(),
    )
    targets = planner.targets_for_value_change(level.value_key)
    contribution_target = next(
        item for item in targets if item.kind == "visual_contribution"
    )
    assert contribution_target.panel_id == panel.id
    assert contribution_target.view_id is None


def test_grid_slice_lowers_operator_and_bound_line_plot():
    inline._reset_authoring_app()
    field = np.zeros((4, 5), dtype=np.float32)

    source = cnv.source()
    axis = source.dropdown("slice_axis", label="Axis", options=("x", "y"), default="x")
    position = source.slider("slice_position", label="Position", min=0.0, max=1.0)
    surface = source.surface(
        "Landscape",
        values=field,
        x=np.arange(5, dtype=np.float32),
        y=np.arange(4, dtype=np.float32),
    )
    # The grid slice produces plain data (+ the surface overlay); a separate line
    # widget consumes it, no different from any other field source.
    slice_data = source.grid_slice(
        "Profile",
        surface=surface,
        axis=axis,
        position=position,
        overlay={"fill_alpha": 0.1},
    )
    profile = source.line("Profile line", source=slice_data, x=None)
    cnv.layout(((surface, profile), (source.controls_panel,)))
    app_spec = _lower(source)

    operators = tuple(app_spec.view_catalog.operators.values())
    grid_slices = [
        op
        for op in operators
        if isinstance(op, OperatorSpec) and op.kind == "grid_slice"
    ]
    assert len(grid_slices) == 1
    operator = grid_slices[0]
    contributions = tuple(app_spec.view_catalog.contributions.values())
    assert len(contributions) == 1
    overlay = contributions[0]
    assert overlay.kind == "grid_slice_overlay"
    assert overlay.capability == "scene3d.layers/v1"
    assert overlay.inputs["slice"] == operator.id

    # The slice is driven by runtime values, so both keys must survive lowering.
    assert operator.inputs["field"]
    assert operator.properties["axis"].key == axis.value_key
    assert operator.properties["position"].key == position.value_key

    # The slice line is a standalone view whose data source *is* the operator:
    # from the line's point of view a grid slice is just another input, no
    # different from a stored field.
    views = tuple(app_spec.view_catalog.views.values())
    assert any(
        isinstance(view, ViewSpec) and view.kind == "surface" for view in views
    )
    slice_plots = [
        view
        for view in views
        if isinstance(view, ViewSpec)
        and view.kind == "line_plot"
        and view.inputs.get("data") == operator.id
    ]
    assert len(slice_plots) == 1


def test_grid_slice_visual_contribution_owns_overlay_refresh():
    """GridSlice owns an instance-addressed scene contribution; Surface only
    refreshes its own visual and axes."""
    from compneurovis.frontends.vispy.builtins import register_first_party_vispy
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner

    register_first_party_vispy()
    inline._reset_authoring_app()
    field = np.zeros((4, 5), dtype=np.float32)
    source = cnv.source()
    axis = source.dropdown("slice_axis", label="Axis", options=("x", "y"), default="x")
    position = source.slider("slice_position", label="Position", min=0.0, max=1.0)
    surface = source.surface(
        "Landscape",
        values=field,
        x=np.arange(5, dtype=np.float32),
        y=np.arange(4, dtype=np.float32),
    )
    slice_data = source.grid_slice(
        "Profile",
        surface=surface,
        axis=axis,
        position=position,
        overlay={"fill_alpha": 0.1},
    )
    profile = source.line("Profile line", source=slice_data, x=None)
    cnv.layout(((surface, profile), (source.controls_panel,)))
    app = _lower(source)

    planner = RefreshPlanner(app, lambda: app.layout_catalog.active_layout())
    op = next(
        o
        for o in app.view_catalog.operators.values()
        if isinstance(o, OperatorSpec) and o.kind == "grid_slice"
    )
    contribution = next(iter(app.view_catalog.contributions.values()))
    surface_view = next(
        v
        for v in app.view_catalog.views.values()
        if isinstance(v, ViewSpec) and v.kind == "surface"
    )
    surface_field = surface_view.inputs["field"]
    surface_panel = app.layout_catalog.active_layout().panel_for_view(
        surface_view.id
    )
    assert surface_panel is not None

    def surface_kinds(targets):
        return {
            target.kind
            for target in targets
            if str(target.view_id) == surface_view.id
            or (
                target.kind == "visual_contribution"
                and target.panel_id == surface_panel.id
            )
        }

    # Cut-line appearance change → overlay only (not the data-consuming line).
    assert surface_kinds(
        planner.targets_for_visual_contribution_patch(contribution.id)
    ) == {"visual_contribution"}
    # A compute-relevant change → overlay AND the consuming line (standalone).
    op_axis = planner.targets_for_operator_patch(op.id, {"axis"})
    assert surface_kinds(op_axis) == {"visual_contribution"}
    assert any(t.kind == "view" for t in op_axis)
    # Driving the slice control refreshes its overlay.
    assert "visual_contribution" in surface_kinds(
        planner.targets_for_value_change(axis.value_key)
    )
    # Replacing the surface field rebuilds the surface visual + axes + overlay
    # (surface's registered field-replace hook + the operator contributor).
    assert {
        "surface_visual",
        "surface_axes_geometry",
        "visual_contribution",
    } <= surface_kinds(planner.targets_for_field_replace(surface_field))


def test_network2d_lowers_through_the_canonical_view_path():
    inline._reset_authoring_app()

    source = cnv.source()
    scheme = source.network2d(
        "Scheme",
        nodes={"A": (0.0, 0.0), "B": (1.0, 1.0)},
        edges=(("A", "B", "A->B"),),
        node_values=(0.25, 0.75),
        edge_values=(0.5,),
    )
    cnv.layout(((scheme,),))
    app_spec = _lower(source)

    views = tuple(app_spec.view_catalog.views.values())
    canonical_views = [view for view in views if isinstance(view, ViewSpec)]
    assert len(canonical_views) == 1
    view = canonical_views[0]
    assert view.kind == "network2d"

    # Nodes and edges are declared as ordinary fields, so both must exist.
    assert set(view.inputs) == {"nodes", "edges"}
    for field_id in view.inputs.values():
        assert field_id in app_spec.data.fields


_PURE_PYTHON_EXAMPLE_DIRS = ("widgets", "surface_plot", "custom")


def _pure_python_examples() -> list[Path]:
    root = Path(__file__).resolve().parents[1] / "examples"
    return sorted(
        path
        for directory in _PURE_PYTHON_EXAMPLE_DIRS
        for path in (root / directory).glob("*.py")
    )


@pytest.mark.parametrize(
    "example",
    _pure_python_examples(),
    ids=lambda path: f"{path.parent.name}/{path.stem}",
)
def test_example_lowers(example: Path, monkeypatch: pytest.MonkeyPatch):
    """Every simulator-free example must still compile to an AppSpec.

    Examples are the widest real use of the authoring API, so this is the net
    that catches an authoring-surface rename that the unit tests miss.
    """
    inline._reset_authoring_app()
    captured: dict = {}

    def fake_show(*args, **kwargs):
        sources = inline._current_authoring_app()._sources
        assert sources, f"{example.name} registered no source"
        captured["sources"] = len(sources)
        if len(sources) == 1:
            source = sources[0]
            source._panel_grid = inline._current_authoring_app()._panel_grid
            captured["app_spec"] = source._build_app_spec_for_backend(
                source._make_backend()
            )
        return None

    monkeypatch.setattr(cnv, "show", fake_show)
    runpy.run_path(str(example), run_name="__main__")

    assert captured.get("sources"), f"{example.name} never reached cnv.show()"
    if captured["sources"] == 1:
        assert captured["app_spec"] is not None


def _drive_ticks(source, ticks: int = 3) -> list[list]:
    """Build the source's backend and drive tick(), returning per-tick payloads.

    Covers what spec-lowering tests cannot: the runtime emission path. Each frame
    is the list of message payloads the backend queued that tick.
    """
    backend = source._make_backend()
    backend.initialize(None)
    frames: list[list] = []
    for _ in range(ticks):
        backend.tick()
        frames.append([message.payload for message in backend.take_outbound_messages()])
    return frames


def test_inline_backend_tick_emits_series_surface_and_value_updates():
    from compneurovis.core.messages import FieldAppend, FieldReplace, ValueChange

    inline._reset_authoring_app()
    state = {"t": 0.0, "v": 0.0}

    def step(ctx):
        state["t"] += 1.0
        state["v"] = 2.0 * state["t"]

    source = cnv.source(step)
    source.line("Signal", read=lambda: state["v"], x=lambda: state["t"])
    source.surface(
        "Field",
        read=lambda: np.full((2, 3), state["t"], dtype=np.float32),
        x=np.arange(3, dtype=np.float32),
        y=np.arange(2, dtype=np.float32),
    )
    source.derive_value("energy", lambda: state["v"] ** 2, max_refresh_hz=None)

    frames = _drive_ticks(source, ticks=2)

    # Every tick: the line appends a sample, the surface replaces its field, and
    # the derived value publishes. These are the three producer message kinds.
    for frame in frames:
        kinds = [type(payload) for payload in frame]
        assert FieldAppend in kinds, f"no series append in {kinds}"
        assert FieldReplace in kinds, f"no surface replace in {kinds}"
        assert ValueChange in kinds, f"no derived value change in {kinds}"

    # The derived value tracks state: v = 2t, energy = v^2 = (2*2)^2 = 16 at t=2.
    last_value_change = next(
        payload for payload in reversed(frames[-1]) if isinstance(payload, ValueChange)
    )
    assert last_value_change.updates["energy"] == pytest.approx(16.0)


def test_context_series_gives_any_widget_append_data():
    """A widget authored only through `context` can own streaming append-data.

    Phase 4 de-privilege: previously only `line` could produce `FieldAppend`
    (time-series) data. Now a third-party-style `Widget` gets it via
    `context.series`, on the same public path as `context.data`.
    """
    from compneurovis.core.messages import FieldAppend
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_authoring_app()
    state = {"t": 0.0}

    def step(ctx):
        state["t"] += 1.0

    class Rolling(Widget[PanelRef]):
        def declare(self, context) -> PanelRef:
            data = context.series(
                "signal", read=lambda: state["t"], x=lambda: state["t"]
            )
            return context.view("rolling", "Rolling", inputs={"trace": data})

    source = cnv.source(step)
    ref = source.add(Rolling())
    assert isinstance(ref, PanelRef)
    cnv.layout(((ref,),))

    # Lowers through the canonical path: a view plus its declared field.
    app_spec = _lower(source)
    views = tuple(app_spec.view_catalog.views.values())
    rolling = [
        v for v in views if isinstance(v, ViewSpec) and v.kind == "rolling"
    ]
    assert len(rolling) == 1
    assert app_spec.data.fields  # the series field was declared

    # And it streams append-data on tick — the capability that used to be line-only.
    frames = _drive_ticks(source, ticks=2)
    for frame in frames:
        assert any(isinstance(p, FieldAppend) for p in frame), frame


def test_context_view_can_declare_a_native_panel_kind():
    """A third-party widget can declare a first-class panel kind (e.g. 3-D).

    `context.view` does not hardcode a standalone panel;
    the widget picks the panel category the built-ins use.
    """
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_authoring_app()

    class Solid(Widget[PanelRef]):
        def declare(self, context) -> PanelRef:
            data = context.data(
                "v", values=np.zeros(3, dtype=np.float32), labels=("a", "b", "c")
            )
            return context.view(
                "solid", "Solid", inputs={"v": data}, panel_kind="scene_3d"
            )

    source = cnv.source()
    ref = source.add(Solid())
    cnv.layout(((ref,),))
    app_spec = _lower(source)

    panels = app_spec.layout_catalog.active_layout().panels
    panel = next(p for p in panels if p.id == ref.id)
    assert panel.kind == "scene_3d"


def test_third_party_widget_reaches_surface_class_capabilities():
    """Capability benchmark, in miniature: a widget authored only through
    `context` gets surface-class data + panel — a 2-D coordinate field in a
    native 3-D panel — with no private hook or first-class ViewSpec.
    """
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_authoring_app()

    class Terrain(Widget[PanelRef]):
        def declare(self, context) -> PanelRef:
            field = context.grid(
                "terrain",
                values=np.zeros((4, 5), dtype=np.float32),
                x=np.arange(5, dtype=np.float32),
                y=np.arange(4, dtype=np.float32),
            )
            return context.view(
                "terrain", "Terrain", inputs={"z": field}, panel_kind="scene_3d"
            )

    source = cnv.source()
    ref = source.add(Terrain())
    cnv.layout(((ref,),))
    app_spec = _lower(source)

    panels = app_spec.layout_catalog.active_layout().panels
    panel = next(p for p in panels if p.id == ref.id)
    assert panel.kind == "scene_3d"
    grid_field = next(
        f for f in app_spec.data.fields.values() if f.id.endswith("_grid")
    )
    assert len(grid_field.dims) == 2


def test_public_geometry_is_neutral_scoped_and_transportable():
    """Two third-party-style widgets lower without package class identity."""
    from multiprocessing.reduction import ForkingPickler

    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_authoring_app()

    class PointCloudFixture(Widget[PanelRef]):
        def __init__(self, offset: float) -> None:
            self.offset = offset

        def declare(self, context) -> PanelRef:
            positions = np.array(
                [
                    [self.offset, 0.0, 0.0],
                    [self.offset, 1.0, 0.0],
                ],
                dtype=np.float32,
            )
            geometry = context.geometry(
                "point_cloud",
                "Cloud",
                data={
                    "positions": positions,
                    "entity_ids": ("a", "b"),
                },
            )
            values = context.data(
                "Cloud values",
                values=np.array([0.25, 0.75], dtype=np.float32),
                labels=("a", "b"),
            )
            selection = context.selection(
                "Cloud entities",
                geometry=geometry,
                initial="a",
            )
            return context.view(
                "point_cloud_3d",
                "Cloud",
                inputs={"values": values},
                geometries={"points": geometry},
                selections={"entities": selection},
                panel_kind="scene_3d",
            )

    source = cnv.source()
    cloud_a = source.add(PointCloudFixture(0.0))
    cloud_b = source.add(PointCloudFixture(10.0))
    cnv.layout(((cloud_a, cloud_b),))
    app = _lower(source)

    geometries = tuple(app.data.geometries.values())
    assert len(geometries) == 2
    assert all(isinstance(item, cnv.GeometrySpec) for item in geometries)
    assert all(item.kind == "point_cloud" for item in geometries)
    assert geometries[0].id != geometries[1].id
    assert all(not item.data["positions"].flags.writeable for item in geometries)

    views = [
        view
        for view in app.view_catalog.views.values()
        if isinstance(view, ViewSpec) and view.kind == "point_cloud_3d"
    ]
    assert len(views) == 2
    assert {view.geometries["points"] for view in views} == {
        geometry.id for geometry in geometries
    }
    selections = tuple(app.interactions.selections.values())
    assert len(selections) == 2
    assert selections[0].id != selections[1].id
    assert {selection.target_id for selection in selections} == {
        geometry.id for geometry in geometries
    }
    assert all(selection.initial == ("a",) for selection in selections)
    assert {view.selections["entities"] for view in views} == {
        selection.id for selection in selections
    }

    transported = ForkingPickler.loads(ForkingPickler.dumps(app))
    assert all(
        isinstance(item, cnv.GeometrySpec)
        for item in transported.data.geometries.values()
    )

    with pytest.raises(TypeError, match="language-neutral spec data"):
        cnv.GeometrySpec(
            id="bad",
            kind="point_cloud",
            data={"callback": lambda: None},
        )


def test_third_party_panel_kind_is_first_class():
    """The validator has zero hardcoded knowledge of panel kinds.

    A novel panel kind the core has never heard of validates purely because its
    view *declares* it (`view.panel_kind == panel.kind`) — no isinstance ladder,
    no blessed-type list, no "unsupported panel kind" rejection. This is the
    property that makes third-party widgets first-class.
    """
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_authoring_app()

    class Exotic(Widget[PanelRef]):
        def declare(self, context) -> PanelRef:
            data = context.data(
                "v", values=np.zeros(2, dtype=np.float32), labels=("a", "b")
            )
            return context.view(
                "exotic", "Exotic", inputs={"v": data}, panel_kind="holographic"
            )

    source = cnv.source()
    ref = source.add(Exotic())
    cnv.layout(((ref,),))
    app_spec = _lower(source)  # pre-refactor this raised "unsupported panel kind"

    panel = next(
        p for p in app_spec.layout_catalog.active_layout().panels if p.id == ref.id
    )
    assert panel.kind == "holographic"


def test_refresh_schema_is_kind_keyed_and_standalone_hosts_refresh_as_one_unit():
    """3-D schemas are kind keyed; a standalone QWidget is one refresh unit."""
    from compneurovis.frontends.vispy.builtins import register_first_party_vispy
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    register_first_party_vispy()
    # Built-in: the kind-keyed lookup still routes a color_map change to the
    # surgical surface_style target (behavior preserved).
    inline._reset_authoring_app()
    src = cnv.source()
    surf = src.surface("S", values=np.zeros((3, 4), dtype=np.float32))
    cnv.layout(((surf,),))
    app = _lower(src)
    planner = RefreshPlanner(app, lambda: app.layout_catalog.active_layout())
    sview = next(
        v
        for v in app.view_catalog.views.values()
        if isinstance(v, ViewSpec) and v.kind == "surface"
    )
    assert "surface_style" in {
        t.kind for t in planner.targets_for_view_patch(sview.id, {"color_map"})
    }

    # Third-party view kind: its QWidget host is the refresh unit.
    inline._reset_authoring_app()

    class Spectro(Widget[PanelRef]):
        def declare(self, context) -> PanelRef:
            data = context.grid("stft", values=np.zeros((2, 3), dtype=np.float32))
            return context.view("spectrogram_test", "Spectro", inputs={"z": data})

    src2 = cnv.source()
    ref = src2.add(Spectro())
    cnv.layout(((ref,),))
    app2 = _lower(src2)
    planner2 = RefreshPlanner(app2, lambda: app2.layout_catalog.active_layout())
    eview = next(
        v for v in app2.view_catalog.views.values() if isinstance(v, ViewSpec)
    )
    assert {t.kind for t in planner2.targets_for_view_patch(eview.id, {"dpi"})} == {
        "view"
    }
