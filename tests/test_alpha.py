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
