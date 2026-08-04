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
    BarPlotViewSpec,
    ExtensionViewSpec,
    GridSliceOperatorSpec,
    LayoutCatalog,
    LayoutSpec,
    LinePlotViewSpec,
    MorphologyViewSpec,
    PanelSpec,
    SurfaceViewSpec,
    ViewCatalog,
    build_default_layout,
)


def _lower(source):
    source._panel_grid = inline._app._panel_grid
    backend = source._make_backend()
    return source._build_app_spec_for_backend(backend)


def test_public_alpha_surface():
    assert all(hasattr(cnv, name) for name in ("source", "layout", "show", "neuron", "jaxley"))
    assert all(not hasattr(cnv, name) for name in ("compose", "remote", "remote_actor"))
    assert callable(cnv.experimental.compose)


def test_core_layout_and_reference_contracts():
    layouts = LayoutCatalog(
        layouts={"compact": LayoutSpec(), "wide": LayoutSpec()},
        active="wide",
    )
    assert layouts.active == "wide"

    bars = BarPlotViewSpec(id="rates", field_id="rates")
    default_layout = build_default_layout(views={bars.id: bars})
    assert [(panel.id, panel.kind) for panel in default_layout.panels] == [
        ("rates-panel", "bar_plot")
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
    assert any(isinstance(view, LinePlotViewSpec) for view in views)
    assert any(isinstance(view, BarPlotViewSpec) for view in views)
    assert any(isinstance(view, SurfaceViewSpec) for view in views)
    assert len(app_spec.interactions.controls) == 1
    assert next(iter(app_spec.interactions.controls.values())).label == "Gain"
    assert len(app_spec.interactions.actions) == 1
    assert next(iter(app_spec.interactions.actions.values())).label == "Reset"
    assert app_spec.layout_catalog.active_layout().panel_grid == (
        (trace.id, surface.id),
        (bars.id, source.controls_panel.id),
    )


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

        app_spec = _lower(source)
        views = tuple(app_spec.view_catalog.views.values())
        assert any(isinstance(view, MorphologyViewSpec) for view in views)
        assert any(isinstance(view, LinePlotViewSpec) for view in views)
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
    profile = source.grid_slice(
        "Profile",
        surface=surface,
        axis=axis,
        position=position,
        overlay={"fill_alpha": 0.1},
    )
    cnv.layout(((surface, profile), (source.controls_panel,)))
    app_spec = _lower(source)

    operators = tuple(app_spec.view_catalog.operators.values())
    grid_slices = [op for op in operators if isinstance(op, GridSliceOperatorSpec)]
    assert len(grid_slices) == 1
    operator = grid_slices[0]

    # The slice is driven by runtime values, so both keys must survive lowering.
    assert operator.axis_value_key == axis.value_key
    assert operator.position_value_key == position.value_key

    # The slice panel is a line plot bound to the operator, not to a raw field.
    views = tuple(app_spec.view_catalog.views.values())
    assert any(isinstance(view, SurfaceViewSpec) for view in views)
    slice_plots = [
        view
        for view in views
        if isinstance(view, LinePlotViewSpec) and view.operator_id == operator.id
    ]
    assert len(slice_plots) == 1


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
            data = context.series("signal", read=lambda: state["t"], x=lambda: state["t"])
            return context.view("rolling", "Rolling", inputs={"trace": data})

    source = cnv.source(step)
    ref = source.add(Rolling())
    assert isinstance(ref, PanelRef)
    cnv.layout(((ref,),))

    # Lowers through the public extension path: an extension view + declared field.
    app_spec = _lower(source)
    views = tuple(app_spec.view_catalog.views.values())
    rolling = [v for v in views if isinstance(v, ExtensionViewSpec) and v.kind == "rolling"]
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
    grid_field = next(f for f in app_spec.data.fields.values() if f.id.endswith("_grid"))
    assert len(grid_field.dims) == 2


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


def test_refresh_schema_is_kind_keyed_and_registerable():
    """Refresh schemas are keyed by `view.kind`, not `type(view)`.

    Built-in surgical refresh is preserved through the kind key, and a third-party
    view kind can register its own schema to get surgical refresh in place of the
    blanket host repaint — the capability that was built-in-only.
    """
    from compneurovis.frontends.vispy.refresh_planning import (
        RefreshPlanner,
        register_view_refresh_schema,
    )
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
        v for v in app.view_catalog.views.values() if isinstance(v, SurfaceViewSpec)
    )
    assert "surface_style" in {
        t.kind for t in planner.targets_for_view_patch(sview.id, {"color_map"})
    }

    # Third-party kind: blanket host repaint by default, surgical after registering.
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
    register_view_refresh_schema("spectrogram_test", patch={"spec_axes": frozenset({"dpi"})})
    assert {t.kind for t in planner2.targets_for_view_patch(eview.id, {"dpi"})} == {
        "spec_axes"
    }
