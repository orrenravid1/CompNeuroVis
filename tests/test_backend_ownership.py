from __future__ import annotations

from importlib.util import find_spec, module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import numpy as np
import pytest


@pytest.mark.skipif(find_spec("neuron") is None, reason="NEURON is not installed")
def test_neuron_visual_geometry_fallback_does_not_mutate_pt3d():
    from neuron import h

    from compneurovis.backends.neuron.geometry import build_morphology_geometry

    h("forall delete_section()")
    try:
        detailed = h.Section(name="detailed")
        missing = h.Section(name="missing")
        missing.connect(detailed(1.0))
        missing.L = 25.0
        missing.diam = 3.0
        h.pt3dclear(sec=detailed)
        h.pt3dadd(1.0, 2.0, 3.0, 4.0, sec=detailed)
        h.pt3dadd(4.0, 6.0, 3.0, 2.0, sec=detailed)
        before = tuple(
            (
                detailed.x3d(i),
                detailed.y3d(i),
                detailed.z3d(i),
                detailed.diam3d(i),
            )
            for i in range(int(detailed.n3d()))
        )

        geometry = build_morphology_geometry((detailed, missing))

        after = tuple(
            (
                detailed.x3d(i),
                detailed.y3d(i),
                detailed.z3d(i),
                detailed.diam3d(i),
            )
            for i in range(int(detailed.n3d()))
        )
        assert after == before
        assert int(missing.n3d()) == 0
        assert geometry.section_names == ("detailed", "missing")
        assert geometry.lengths.tolist() == pytest.approx([5.0, 25.0])
    finally:
        h("forall delete_section()")


@pytest.mark.skipif(find_spec("neuron") is None, reason="NEURON is not installed")
def test_neuron_reset_discards_pending_samples_with_segment_sampling():
    from neuron import h

    from compneurovis.backends.neuron.backend import (
        NeuronBackend,
        SegmentSamplingConfig,
    )
    from compneurovis.core.messages import Reset, command_message

    class SamplingBackend(NeuronBackend):
        def build_sections(self):
            return [h.Section(name="reset_soma")]

    h("forall delete_section()")
    try:
        backend = SamplingBackend(
            segment_sampling=SegmentSamplingConfig(lambda segment: segment._ref_v)
        )
        backend.build_startup_data()
        backend._pending_times = [1.0]
        backend._pending_steps = [np.asarray([-60.0], dtype=np.float32)]
        backend._pending_recorded = [np.asarray([-60.0], dtype=np.float32)]

        backend.handle(command_message(Reset()))

        assert backend._pending_times == []
        assert backend._pending_steps == []
        assert backend._pending_recorded == []
        assert backend._last_flush_t == pytest.approx(0.0)
    finally:
        h("forall delete_section()")


@pytest.mark.parametrize(
    ("dt", "display_dt", "expected_advances"),
    (
        (0.025, 0.1, 4),
        (0.1, 0.1, 1),
        (0.367, 0.1, 1),
    ),
)
def test_neuron_tick_tolerates_simulation_time_roundoff_at_frame_boundary(
    dt, display_dt, expected_advances
):
    from compneurovis.backends.neuron.backend import NeuronBackend

    class FloatingTimeBackend(NeuronBackend):
        def __init__(self):
            super().__init__(dt=dt, display_dt=display_dt)
            self.time = 0.0
            self.advance_count = 0

        def build_sections(self):
            return []

        def _current_sim_time(self) -> float:
            return self.time

        def _advance(self) -> None:
            self.advance_count += 1
            self.time = np.nextafter(self.time + self.dt, float("-inf"))

    backend = FloatingTimeBackend()
    backend.tick()

    assert backend.advance_count == expected_advances


def test_neuron_section_name_lookup_is_cached_for_runtime_bindings():
    from compneurovis.backends.neuron.backend import NeuronBackend

    class CountingSection:
        def __init__(self):
            self.name_calls = 0

        def name(self):
            self.name_calls += 1
            return "soma"

    class LookupBackend(NeuronBackend):
        def build_sections(self):
            return []

    section = CountingSection()
    backend = LookupBackend()
    backend.sections = [section]

    first = backend.sections_by_name()
    second = backend.sections_by_name()

    assert first is second
    assert first == {"soma": section}
    assert section.name_calls == 1


def test_jaxley_display_sampling_preserves_user_recordings(monkeypatch):
    from compneurovis.backends.jaxley import backend as backend_module

    class FakeColumn:
        def to_numpy(self, dtype=None):
            return np.asarray([0, 1], dtype=dtype)

    class FakeNodes:
        def sort_values(self, _name):
            return self

        def __getitem__(self, name):
            assert name == "global_comp_index"
            return FakeColumn()

    class FakeCell:
        meta_name = "cell"

    class FakeNetwork:
        def __init__(self):
            self.recordings = []
            self.nodes = FakeNodes()
            self.xyzr = None
            self.externals = {}
            self.external_inds = {}

        def set(self, _name, _value):
            return None

        def init_states(self):
            return None

        def to_jax(self):
            return None

        def get_parameters(self):
            return []

        def delete_recordings(self):
            raise AssertionError("CompNeuroVis must not delete user recordings")

        def record(self, *_args, **_kwargs):
            raise AssertionError("display sampling must not commandeer recordings")

    config_updates = []
    fake_jax = ModuleType("jax")
    fake_jax.config = SimpleNamespace(
        update=lambda *args, **kwargs: config_updates.append((args, kwargs))
    )
    fake_jaxley = ModuleType("jaxley")
    fake_jaxley.Cell = FakeCell
    fake_integrate = ModuleType("jaxley.integrate")

    def build_init_and_step_fn(_network):
        def initialize(_params, all_states=None, **_kwargs):
            state = (
                {"v": np.asarray([-70.0, -60.0])}
                if all_states is None
                else all_states
            )
            return state, {}

        return initialize, lambda state, *_args, **_kwargs: state

    fake_integrate.build_init_and_step_fn = build_init_and_step_fn
    monkeypatch.setitem(sys.modules, "jax", fake_jax)
    monkeypatch.setitem(sys.modules, "jaxley", fake_jaxley)
    monkeypatch.setitem(sys.modules, "jaxley.integrate", fake_integrate)
    geometry = SimpleNamespace(
        id="morphology",
        entity_ids=("cell@0", "cell@1"),
    )
    monkeypatch.setattr(
        backend_module,
        "build_morphology_geometry",
        lambda *_args, **_kwargs: geometry,
    )
    network = FakeNetwork()

    class RecordingBackend(backend_module.JaxleyBackend):
        def build_cells(self):
            return FakeCell()

        def build_network(self, _cells):
            return network

        def setup_model(self, configured_network, _cells):
            configured_network.recordings.append(("v", 1))

    backend = RecordingBackend()
    values = backend._initialize_model()

    assert network.recordings == [("v", 1)]
    assert values.tolist() == pytest.approx([-70.0, -60.0])
    assert backend._display_indices.tolist() == [0, 1]
    assert config_updates == []


def test_neuron_swc_module_import_does_not_load_hoc(monkeypatch):
    class HocLoadGuard:
        def load_file(self, _path):
            raise AssertionError("importing the SWC module must not load hoc files")

    fake_neuron = ModuleType("neuron")
    fake_neuron.h = HocLoadGuard()
    monkeypatch.setitem(sys.modules, "neuron", fake_neuron)
    source_path = (
        Path(__file__).parents[1]
        / "src"
        / "compneurovis"
        / "backends"
        / "neuron"
        / "io"
        / "swc.py"
    )
    spec = spec_from_file_location("_cnv_swc_import_test", source_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)

    spec.loader.exec_module(module)


@pytest.mark.skipif(find_spec("neuron") is None, reason="NEURON is not installed")
def test_load_swc_neuron_returns_only_owned_sections(tmp_path):
    from neuron import h

    from compneurovis.backends.neuron.geometry import build_morphology_geometry
    from compneurovis.backends.neuron.io.swc import load_swc_neuron

    swc_path = tmp_path / "cell.swc"
    swc_path.write_text(
        "1 1 0 0 0 5 -1\n"
        "2 3 0 5 0 1 1\n"
        "3 3 0 10 0 1 2\n",
        encoding="utf-8",
    )
    h("forall delete_section()")
    try:
        # Match an imported name deliberately. Independent models may contain
        # distinct sections with the same public names.
        existing = h.Section(name="soma[0]")

        imported = load_swc_neuron(swc_path)

        assert imported
        assert all(section is not existing for section in imported)
        assert any(
            section.name().startswith("compneurovis_imported_cell.soma[")
            for section in imported
        )
        assert all(" object at 0x" not in section.name() for section in imported)
        assert set(imported).issubset(set(h.allsec()))
        geometry = build_morphology_geometry(imported)
        assert any(
            entity_id.startswith("soma[0]@")
            for entity_id in geometry.entity_ids
        )

        imported_again = load_swc_neuron(swc_path)
        assert imported_again
        assert set(imported).isdisjoint(set(imported_again))
        assert {section.name() for section in imported_again} == {
            section.name() for section in imported
        }
        assert existing in set(h.allsec())
    finally:
        h("forall delete_section()")
