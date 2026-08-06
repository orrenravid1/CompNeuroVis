from __future__ import annotations

import runpy
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest

import compneurovis as cnv
import compneurovis.inline as inline
from compneurovis.core import (
    AppFragmentSpec,
    AppRef,
    AppSpec,
    ExtensionOperatorSpec,
    ExtensionViewSpec,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ViewCatalog,
    build_default_layout,
)


def _lower(source):
    source._panel_grid = inline._app._panel_grid
    backend = source._make_backend()
    return source._build_app_spec_for_backend(backend)


def test_public_alpha_surface():
    assert all(
        hasattr(cnv, name) for name in ("source", "layout", "show", "neuron", "jaxley")
    )
    assert all(not hasattr(cnv, name) for name in ("compose", "remote", "remote_actor"))
    assert callable(cnv.experimental.compose)


def test_core_layout_and_reference_contracts():
    layouts = LayoutCatalog(
        layouts={"compact": LayoutSpec(), "wide": LayoutSpec()},
        active="wide",
    )
    assert layouts.active == "wide"

    # A view declares its own panel kind; build_default_layout makes a panel of
    # that kind. Bars are extension views now (kind="bar_plot", panel "extension").
    view = ExtensionViewSpec(id="rates", kind="bar_plot")
    default_layout = build_default_layout(views={view.id: view})
    assert [(panel.id, panel.kind) for panel in default_layout.panels] == [
        ("rates-panel", "extension")
    ]

    assert AppRef("field", fragment_id="source").flat_id() == "source:field"
    with pytest.raises(ValueError, match="cannot contain"):
        AppRef("source:field")


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
                "points": cnv.ExtensionGeometrySpec(
                    id="points",
                    kind="test_points",
                    data={
                        "positions": np.zeros((2, 3), dtype=np.float32),
                    },
                ),
            },
        ),
    )
    operator = cnv.ExtensionOperatorSpec(
        id="project",
        kind="identity",
        inputs={"source": AppRef("samples", fragment_id="source")},
        geometries={"domain": AppRef("points", fragment_id="source")},
    )
    view = ExtensionViewSpec(
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

    invalid_operator = cnv.ExtensionOperatorSpec(
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
    inline._reset_inline_session()
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
    # A ``read=`` series line is now a first-class extension view (rendered via
    # the same registry a third-party widget uses), not a typed LinePlotViewSpec.
    assert any(
        isinstance(view, ExtensionViewSpec) and view.kind == "line_plot"
        for view in views
    )
    assert any(
        isinstance(view, ExtensionViewSpec) and view.kind == "bar_plot"
        for view in views
    )
    assert any(
        isinstance(view, ExtensionViewSpec) and view.kind == "surface" for view in views
    )
    assert len(app_spec.interactions.controls) == 1
    assert next(iter(app_spec.interactions.controls.values())).label == "Gain"
    assert len(app_spec.interactions.actions) == 1
    assert next(iter(app_spec.interactions.actions.values())).label == "Reset"
    assert app_spec.layout_catalog.active_layout().panel_grid == (
        (trace.id, surface.id),
        (bars.id, source.controls_panel.id),
    )


def test_surface_field_is_the_single_owner_of_grid_coordinates():
    """Surface scene geometry comes from its field, with no duplicate grid spec."""
    from multiprocessing.reduction import ForkingPickler

    from compneurovis.frontends.vispy.view_inputs.surface import (
        surface_scene_from_field,
    )

    inline._reset_inline_session()
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
        if isinstance(candidate, ExtensionViewSpec) and candidate.kind == "surface"
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
        if isinstance(candidate, ExtensionViewSpec) and candidate.kind == "surface"
    )
    transported_field = transported_app.data.fields[transported_view.inputs["field"]]
    assert transported_field.dims == ("latitude", "longitude")
    np.testing.assert_array_equal(transported_field.coords["longitude"], x)
    np.testing.assert_array_equal(transported_field.coords["latitude"], y)


def test_bound_level_marker_in_extension_properties_triggers_refresh():
    """A control-bound reference line survives the migration to extension views.

    A migrated line's ``levels`` live in ``ExtensionViewSpec.properties`` as
    ``LevelMarker`` dataclasses whose ``value`` may be a binding. The refresh
    planner must still detect that on a value change -- via the generic
    dataclass descent in ``_contains_binding``, not any level-specific code --
    or a bound reference line would silently stop tracking its control.
    """
    from compneurovis.core import ValueBindingSpec
    from compneurovis.core.views import LevelMarker
    from compneurovis.frontends.vispy.refresh_planning import _contains_binding

    properties = {"levels": (LevelMarker(value=ValueBindingSpec(key="threshold")),)}
    assert _contains_binding(properties, "threshold", "root")
    assert not _contains_binding(properties, "unrelated", "root")


def test_register_widget_names_a_source_method():
    """A registered widget gets ``source.<name>(...)`` -- the opt-in named surface
    the built-ins have, available to any (third-party) widget."""
    inline._reset_inline_session()
    from compneurovis import register_widget
    from compneurovis.inline.widgets.api import Widget
    from compneurovis.inline.widgets.source_api import _SOURCE_WIDGETS

    calls = []

    class Probe(Widget):
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs

        def declare(self, context):
            calls.append((self.args, self.kwargs))
            return "PROBE_REF"

    try:
        register_widget("probe", Probe)
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
        _SOURCE_WIDGETS.pop("probe", None)


def test_neuron_source_builds_morphology_and_selection_trace():
    if find_spec("neuron") is None:
        pytest.skip("NEURON extra is not installed")

    from neuron import h

    inline._reset_inline_session()
    h("forall delete_section()")
    try:
        soma = h.Section(name="soma")
        soma.L = soma.diam = 20.0
        soma.insert("hh")

        source = cnv.neuron.source(
            sections=[soma],
            dt=0.025,
            display_dt=0.5,
        )
        morphology = source.morphology(
            variable="v",
            selected="soma@0.50000",
        )
        voltage_data = source.record_selection(
            "Selected voltage",
            selection=morphology.selection,
            variables={"Voltage": "v"},
        )
        voltage = source.line("Selected voltage", source=voltage_data)
        cnv.layout(((morphology, voltage),))

        source._panel_grid = inline._app._panel_grid
        backend = source._make_backend()
        app_spec = source._build_app_spec_for_backend(backend)
        views = tuple(app_spec.view_catalog.views.values())
        morphology_view = next(
            view
            for view in views
            if isinstance(view, ExtensionViewSpec) and view.kind == "morphology"
        )
        assert morphology_view.selections["entities"] == morphology.selected.id
        assert morphology_view.geometries["morphology"]
        assert morphology.selected.id in app_spec.interactions.selections
        assert "_selected" not in app_spec.interactions.selections
        assert any(
            isinstance(view, ExtensionViewSpec) and view.kind == "line_plot"
            for view in views
        )
        from compneurovis.core.messages import (
            EntityClicked,
            ValueChange,
            command_message,
        )

        backend.initialize(app_spec)
        backend.take_outbound_messages()
        backend.handle(
            command_message(EntityClicked(morphology.selected.id, "soma@0.50000"))
        )
        assert backend.values.get(morphology.selected.id) == ["soma@0.50000"]
        selection_updates = [
            message.payload
            for message in backend.take_outbound_messages()
            if isinstance(message.payload, ValueChange)
        ]
        assert selection_updates[-1].updates == {
            morphology.selected.id: ["soma@0.50000"]
        }
    finally:
        h("forall delete_section()")


def test_jaxley_namespace_imports_when_installed():
    if find_spec("jaxley") is None:
        pytest.skip("Jaxley extra is not installed")

    assert callable(cnv.jaxley.source)


def test_grid_slice_lowers_operator_and_bound_line_plot():
    inline._reset_inline_session()
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
        if isinstance(op, ExtensionOperatorSpec) and op.kind == "grid_slice"
    ]
    assert len(grid_slices) == 1
    operator = grid_slices[0]

    # The slice is driven by runtime values, so both keys must survive lowering.
    assert operator.inputs["field"]
    assert operator.properties["axis"].key == axis.value_key
    assert operator.properties["position"].key == position.value_key

    # The slice line is an extension line whose data source *is* the operator:
    # from the line's point of view a grid slice is just another input, no
    # different from a stored field.
    views = tuple(app_spec.view_catalog.views.values())
    assert any(
        isinstance(view, ExtensionViewSpec) and view.kind == "surface" for view in views
    )
    slice_plots = [
        view
        for view in views
        if isinstance(view, ExtensionViewSpec)
        and view.kind == "line_plot"
        and view.inputs.get("data") == operator.id
    ]
    assert len(slice_plots) == 1


def test_grid_slice_operator_refresh_routes_through_registered_contributor():
    """The planner has no operator-kind knowledge: a grid slice's overlay routing
    is owned by the operator's *registered* refresh contributor (installed by the
    vispy frontend, exactly as a third-party operator would register its own).
    """
    import compneurovis.frontends.vispy.view3d.visuals  # noqa: F401  # discovery: registers surface schema + grid-slice operator contributor
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner

    inline._reset_inline_session()
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
        if isinstance(o, ExtensionOperatorSpec) and o.kind == "grid_slice"
    )
    surface_view = next(
        v
        for v in app.view_catalog.views.values()
        if isinstance(v, ExtensionViewSpec) and v.kind == "surface"
    )
    surface_field = surface_view.inputs["field"]

    def surface_kinds(targets):
        return {t.kind for t in targets if str(t.view_id) == surface_view.id}

    # Cut-line appearance change → overlay only (not the data-consuming line).
    assert surface_kinds(planner.targets_for_operator_patch(op.id, {"color"})) == {
        "operator_overlay"
    }
    # A compute-relevant change → overlay AND the consuming line (extension).
    op_axis = planner.targets_for_operator_patch(op.id, {"axis"})
    assert surface_kinds(op_axis) == {"operator_overlay"}
    assert any(t.kind == "extension" for t in op_axis)
    # Driving the slice control refreshes its overlay.
    assert "operator_overlay" in surface_kinds(
        planner.targets_for_value_change(axis.value_key)
    )
    # Replacing the surface field rebuilds the surface visual + axes + overlay
    # (surface's registered field-replace hook + the operator contributor).
    assert {
        "surface_visual",
        "surface_axes_geometry",
        "operator_overlay",
    } <= surface_kinds(planner.targets_for_field_replace(surface_field))


def test_network2d_lowers_through_the_public_extension_path():
    inline._reset_inline_session()

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
    extensions = [view for view in views if isinstance(view, ExtensionViewSpec)]
    assert len(extensions) == 1
    view = extensions[0]
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
    inline._reset_inline_session()
    captured: dict = {}

    def fake_show(*args, **kwargs):
        sources = inline._app._sources
        assert sources, f"{example.name} registered no source"
        captured["sources"] = len(sources)
        if len(sources) == 1:
            source = sources[0]
            source._panel_grid = inline._app._panel_grid
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

    inline._reset_inline_session()
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

    inline._reset_inline_session()
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

    # Lowers through the public extension path: an extension view + declared field.
    app_spec = _lower(source)
    views = tuple(app_spec.view_catalog.views.values())
    rolling = [
        v for v in views if isinstance(v, ExtensionViewSpec) and v.kind == "rolling"
    ]
    assert len(rolling) == 1
    assert app_spec.data.fields  # the series field was declared

    # And it streams append-data on tick — the capability that used to be line-only.
    frames = _drive_ticks(source, ticks=2)
    for frame in frames:
        assert any(isinstance(p, FieldAppend) for p in frame), frame


def test_context_view_can_declare_a_native_panel_kind():
    """An extension widget can declare a first-class panel kind (e.g. 3-D).

    Phase 4 de-privilege: `context.view` no longer hardcodes an extension panel;
    the widget picks the panel category the built-ins use.
    """
    from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_inline_session()

    class Solid(Widget[PanelRef]):
        def declare(self, context) -> PanelRef:
            data = context.data(
                "v", values=np.zeros(3, dtype=np.float32), labels=("a", "b", "c")
            )
            return context.view(
                "solid", "Solid", inputs={"v": data}, panel_kind=PANEL_KIND_VIEW_3D
            )

    source = cnv.source()
    ref = source.add(Solid())
    cnv.layout(((ref,),))
    app_spec = _lower(source)

    panels = app_spec.layout_catalog.active_layout().panels
    panel = next(p for p in panels if p.id == ref.id)
    assert panel.kind == PANEL_KIND_VIEW_3D


def test_extension_widget_reaches_surface_class_capabilities():
    """Capability benchmark, in miniature: a widget authored only through
    `context` gets surface-class data + panel — a 2-D coordinate field in a
    native 3-D panel — with no private hook or first-class ViewSpec.
    """
    from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_inline_session()

    class Terrain(Widget[PanelRef]):
        def declare(self, context) -> PanelRef:
            field = context.grid(
                "terrain",
                values=np.zeros((4, 5), dtype=np.float32),
                x=np.arange(5, dtype=np.float32),
                y=np.arange(4, dtype=np.float32),
            )
            return context.view(
                "terrain", "Terrain", inputs={"z": field}, panel_kind=PANEL_KIND_VIEW_3D
            )

    source = cnv.source()
    ref = source.add(Terrain())
    cnv.layout(((ref,),))
    app_spec = _lower(source)

    panels = app_spec.layout_catalog.active_layout().panels
    panel = next(p for p in panels if p.id == ref.id)
    assert panel.kind == PANEL_KIND_VIEW_3D
    grid_field = next(
        f for f in app_spec.data.fields.values() if f.id.endswith("_grid")
    )
    assert len(grid_field.dims) == 2


def test_public_geometry_is_neutral_scoped_and_transportable():
    """Two third-party-style widgets lower without package class identity."""
    from multiprocessing.reduction import ForkingPickler

    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    inline._reset_inline_session()

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
                panel_kind=cnv.PANEL_KIND_VIEW_3D,
            )

    source = cnv.source()
    cloud_a = source.add(PointCloudFixture(0.0))
    cloud_b = source.add(PointCloudFixture(10.0))
    cnv.layout(((cloud_a, cloud_b),))
    app = _lower(source)

    geometries = tuple(app.data.geometries.values())
    assert len(geometries) == 2
    assert all(isinstance(item, cnv.ExtensionGeometrySpec) for item in geometries)
    assert all(item.kind == "point_cloud" for item in geometries)
    assert geometries[0].id != geometries[1].id
    assert all(not item.data["positions"].flags.writeable for item in geometries)

    views = [
        view
        for view in app.view_catalog.views.values()
        if isinstance(view, ExtensionViewSpec) and view.kind == "point_cloud_3d"
    ]
    assert len(views) == 2
    assert {view.geometries["points"] for view in views} == {
        geometry.id for geometry in geometries
    }
    selections = tuple(app.interactions.selections.values())
    assert len(selections) == 2
    assert selections[0].id != selections[1].id
    assert {selection.geometry_id for selection in selections} == {
        geometry.id for geometry in geometries
    }
    assert all(selection.initial == ("a",) for selection in selections)
    assert {view.selections["entities"] for view in views} == {
        selection.id for selection in selections
    }

    transported = ForkingPickler.loads(ForkingPickler.dumps(app))
    assert all(
        isinstance(item, cnv.ExtensionGeometrySpec)
        for item in transported.data.geometries.values()
    )

    with pytest.raises(TypeError, match="language-neutral spec data"):
        cnv.ExtensionGeometrySpec(
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

    inline._reset_inline_session()

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


def test_refresh_schema_is_kind_keyed_and_extension_hosts_refresh_as_one_unit():
    """3-D schemas are kind keyed; an extension QWidget is one refresh unit."""
    import compneurovis.frontends.vispy.view3d.visuals  # noqa: F401  # discovery: registers built-in surface/morphology schemas
    from compneurovis.frontends.vispy.refresh_planning import RefreshPlanner
    from compneurovis.inline.refs import PanelRef
    from compneurovis.inline.widgets.api import Widget

    # Built-in: the kind-keyed lookup still routes a color_map change to the
    # surgical surface_style target (behavior preserved).
    inline._reset_inline_session()
    src = cnv.source()
    surf = src.surface("S", values=np.zeros((3, 4), dtype=np.float32))
    cnv.layout(((surf,),))
    app = _lower(src)
    planner = RefreshPlanner(app, lambda: app.layout_catalog.active_layout())
    sview = next(
        v
        for v in app.view_catalog.views.values()
        if isinstance(v, ExtensionViewSpec) and v.kind == "surface"
    )
    assert "surface_style" in {
        t.kind for t in planner.targets_for_view_patch(sview.id, {"color_map"})
    }

    # Third-party extension kind: its QWidget host is the refresh unit.
    inline._reset_inline_session()

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
        v for v in app2.view_catalog.views.values() if isinstance(v, ExtensionViewSpec)
    )
    assert {t.kind for t in planner2.targets_for_view_patch(eview.id, {"dpi"})} == {
        "extension"
    }
