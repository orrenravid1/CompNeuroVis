from __future__ import annotations

import numpy as np
import pytest

import compneurovis as cnv
from compneurovis import inline
from compneurovis.core import Field, ViewSpec
from compneurovis.inline.app import InlineApp
from compneurovis.inline.refs import DataRef, PanelRef


def test_show_consumes_the_current_authoring_app(monkeypatch: pytest.MonkeyPatch):
    inline._reset_authoring_app()
    launches = []

    def fake_show(self: InlineApp, *, title: str | None = None):
        launches.append((tuple(self._sources), self._panel_grid, title))
        return title

    monkeypatch.setattr(InlineApp, "show", fake_show)

    first = cnv.source()
    cnv.layout(((PanelRef("first-panel"),),))
    assert cnv.show(title="First") == "First"
    assert inline._current_authoring_app()._sources == []
    assert inline._current_authoring_app()._panel_grid is None

    second = cnv.source()
    assert cnv.show(title="Second") == "Second"

    assert launches == [
        ((first,), (("first-panel",),), "First"),
        ((second,), None, "Second"),
    ]


def test_show_consumes_state_even_if_launch_fails(monkeypatch: pytest.MonkeyPatch):
    inline._reset_authoring_app()
    first = cnv.source()

    def fail_show(self: InlineApp, *, title: str | None = None):
        assert self._sources == [first]
        raise RuntimeError("launch failed")

    monkeypatch.setattr(InlineApp, "show", fail_show)

    with pytest.raises(RuntimeError, match="launch failed"):
        cnv.show()

    assert inline._current_authoring_app()._sources == []
    assert inline._current_authoring_app()._panel_grid is None


def test_data_ref_owns_selector_containers_and_lowers_slices():
    labels = ["axon", "soma"]
    indices = np.asarray([1, 3], dtype=np.int32)
    object_indices = np.empty(1, dtype=object)
    object_indices[0] = [4, 5]
    nested = {"labels": labels, "indices": indices}
    window = slice(1, 8, 2)
    selectors = {
        "segment": labels,
        "indices": indices,
        "object_indices": object_indices,
        "nested": nested,
        "time": window,
    }

    ref = DataRef(_field_id="samples", _selectors=selectors)

    labels.append("dendrite")
    indices[0] = 99
    object_indices[0].append(6)
    nested["new"] = True
    selectors["segment"] = ["changed"]

    assert ref._selectors["segment"] == ("axon", "soma")
    assert ref._selectors["indices"].tolist() == [1, 3]
    assert ref._selectors["indices"].flags.writeable is False
    assert ref._selectors["object_indices"] == ((4, 5),)
    assert ref._selectors["nested"]["labels"] == ("axon", "soma")
    assert ref._selectors["nested"]["indices"].tolist() == [1, 3]
    assert "new" not in ref._selectors["nested"]
    assert ref._selectors["time"] == {
        "kind": "slice",
        "start": 1,
        "stop": 8,
        "step": 2,
    }
    view = ViewSpec(
        id="slice-view",
        kind="test_slice",
        properties={"selectors": ref._selectors},
    )
    assert view.properties["selectors"]["time"] == ref._selectors["time"]
    field = Field(
        id="samples",
        values=np.arange(10),
        dims=("time",),
        coords={"time": np.arange(10)},
    )
    selected = field.select({"time": ref._selectors["time"]})
    assert selected.values.tolist() == [1, 3, 5, 7]
    with pytest.raises(TypeError):
        ref._selectors["segment"] = ("changed",)


def test_direct_source_show_detaches_it_from_the_ambient_app(
    monkeypatch: pytest.MonkeyPatch,
):
    import compneurovis._source_runtime as source_runtime

    inline._reset_authoring_app()
    launched = []

    def fake_launch(source):
        launched.append(source)
        return "launched"

    monkeypatch.setattr(source_runtime, "launch_source", fake_launch)

    source = cnv.source()
    assert source.show() == "launched"
    assert launched == [source]
    assert inline._current_authoring_app()._sources == []


def test_registered_authoring_names_are_reachable_and_factories_return_refs():
    from compneurovis.inline.control_registry import _control_factories
    from compneurovis.inline.widget_registry import _widget_factories
    from compneurovis.widgets import Widget

    class Probe(Widget):
        def declare(self, context):
            del context
            return PanelRef("probe")

    with pytest.raises(ValueError, match="public Python identifier"):
        cnv.register_widget("not valid", Probe)
    with pytest.raises(ValueError, match="public Python identifier"):
        cnv.register_control("class", lambda context: context)
    with pytest.raises(ValueError, match="built-in"):
        cnv.register_widget("title", Probe)
    with pytest.raises(ValueError, match="authoring name"):
        cnv.register_control("id", lambda context: context)

    try:
        cnv.register_control("broken_control", lambda context: 42)
        source = cnv.source()

        with pytest.raises(TypeError, match="must return ControlRef"):
            source.broken_control()

        assert source._controls_panels == {}
    finally:
        _control_factories.pop("broken_control", None)
        _widget_factories.pop("not valid", None)
