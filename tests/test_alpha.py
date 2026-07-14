from __future__ import annotations

from importlib.util import find_spec

import numpy as np
import pytest

import compneurovis as cnv
import compneurovis.inline as inline
from compneurovis.core import (
    AppFragmentSpec,
    AppRef,
    AppSpec,
    BarPlotViewSpec,
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
        voltage = source.line(
            "Selected voltage",
            source=morphology.selection,
            variables={"Voltage": "v"},
        )
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
