from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import numpy as np

import compneurovis as cnv
from compneurovis.inline import authoring as inline


EXAMPLE = Path(__file__).parents[1] / "examples" / "animal_sounds" / "stft_viewer.py"
SPEC = importlib.util.spec_from_file_location("example_stft_viewer", EXAMPLE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
AudioClip = MODULE.AudioClip
STFTViewer = MODULE.STFTViewer


def _load_xeno_canto_module():
    path = EXAMPLE.with_name("xeno_canto.py")
    spec = importlib.util.spec_from_file_location("example_xeno_canto", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("stft_viewer")
    sys.modules[spec.name] = module
    sys.modules["stft_viewer"] = MODULE
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            del sys.modules["stft_viewer"]
        else:
            sys.modules["stft_viewer"] = previous
    return module


def test_stft_viewer_has_fixed_db_surface_and_composes() -> None:
    inline._reset_authoring_app()
    sample_rate = MODULE.TARGET_SAMPLE_RATE
    time_axis = np.arange(sample_rate, dtype=np.float32) / sample_rate
    clip = AudioClip("tone", np.sin(2 * np.pi * 440 * time_axis), sample_rate)
    viewer = STFTViewer(clip, name="Test tone", window_seconds=1.0)

    assert viewer.spectrogram.ndim == 2
    assert viewer.spectrogram.shape == (
        len(viewer.frequencies_khz), len(viewer.times)
    )
    assert float(viewer.spectrogram.min()) >= 0.0
    assert float(viewer.spectrogram.max()) <= 1.0

    source = cnv.source(viewer.step)
    panels = viewer.declare(source)
    cnv.layout(((panels.surface, panels.spectrum), (panels.controls,)))
    app_spec = source._compose_app_spec_for_backend(source._make_backend())

    assert len(tuple(app_spec.iter_view_specs())) == 2
    assert len(tuple(app_spec.iter_operator_specs())) == 1
    surface_view = next(
        view for _, view in app_spec.iter_view_specs() if view.kind == "surface"
    )
    assert surface_view.properties["display_scale"] == (3.0, 1.0, 1.0)
    assert surface_view.properties["camera_orbit_sensitivity"] == 0.75
    assert surface_view.properties["camera_pan_sensitivity"] == 0.5
    assert surface_view.properties["camera_zoom_sensitivity"] == 0.7
    line_view = next(
        view for _, view in app_spec.iter_view_specs() if view.kind == "line_plot"
    )
    assert line_view.properties["color_gradient"][0] == (0.0, "#ff1744")
    assert line_view.properties["color_gradient"][-1] == (1.0, "#b388ff")
    # Play/pause is a trigger control; its shortcut is a separate key binding
    # that invokes it, so hiding or restyling the button cannot disable the key.
    play_pause_ref, play_pause = next(
        (ref, control)
        for ref, control in app_spec.iter_controls()
        if control.label == "Play / pause"
    )
    assert play_pause.value_spec.kind == "trigger"
    assert any(
        binding.shortcuts == ("Space",) and binding.invokes == play_pause_ref.id
        for _, binding in app_spec.iter_key_bindings()
    )


def test_surface_display_scale_preserves_physical_tick_labels() -> None:
    from compneurovis.components.surface.axes import _build_axes_overlay_geometry

    geometry = _build_axes_overlay_geometry(
        axes_in_middle=False,
        tick_count=3,
        tick_length_scale=1.0,
        axis_labels=("Time (s)", "Frequency", "Magnitude"),
        x=np.asarray((0.0, 30.0)),
        y=np.asarray((0.0, 1.0)),
        z=np.asarray((0.0, 1.0)),
        tick_value_scales=(3.0, 1.0, 1.0),
    )

    assert geometry.tick_labels["x"].texts == ["0", "5", "10"]


def test_stft_viewer_load_preserves_surface_shape() -> None:
    sample_rate = MODULE.TARGET_SAMPLE_RATE
    short = AudioClip("short", np.ones(sample_rate // 4), sample_rate)
    long = AudioClip("long", np.ones(sample_rate * 2), sample_rate)
    viewer = STFTViewer(short, window_seconds=1.0)
    shape = viewer.spectrogram.shape

    assert viewer._end_position == 0.25

    viewer.load(long)

    assert viewer.spectrogram.shape == shape
    assert viewer.position == 0.0
    assert viewer._end_position == 1.0


def test_stft_surface_set_data_emits_once_per_loaded_clip() -> None:
    from compneurovis.core.messages import FieldReplace

    inline._reset_authoring_app()
    sample_rate = MODULE.TARGET_SAMPLE_RATE
    first = AudioClip("first", np.ones(sample_rate), sample_rate)
    second = AudioClip("second", -np.ones(sample_rate), sample_rate)
    viewer = STFTViewer(
        first,
        name="Dynamic tone",
        window_seconds=1.0,
    )
    source = cnv.source(viewer.step)
    viewer.declare(source)
    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    backend.initialize(app_spec)
    backend.take_outbound_messages()

    backend.tick()
    assert not any(
        isinstance(message.payload, FieldReplace)
        for message in backend.take_outbound_messages()
    )

    viewer.load(second)
    backend._interaction_context().set_data(viewer.surface_ref, viewer.spectrogram)
    replacements = [
        message.payload
        for message in backend.take_outbound_messages()
        if isinstance(message.payload, FieldReplace)
    ]
    assert len(replacements) == 1
    np.testing.assert_array_equal(replacements[0].values, viewer.spectrogram)

    backend.tick()
    assert not any(
        isinstance(message.payload, FieldReplace)
        for message in backend.take_outbound_messages()
    )


def test_playback_step_publishes_playhead_control_key(monkeypatch) -> None:
    from compneurovis.core.messages import ValueChange

    inline._reset_authoring_app()
    sample_rate = MODULE.TARGET_SAMPLE_RATE
    clip = AudioClip("tone", np.ones(sample_rate), sample_rate)
    viewer = STFTViewer(clip, window_seconds=1.0)
    source = cnv.source(viewer.step)
    viewer.declare(source)
    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    backend.initialize(app_spec)
    backend.take_outbound_messages()

    viewer._playing = True
    viewer._play_started_at = 10.0
    viewer._play_started_position = 0.0
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: 10.5)
    backend.tick()
    updates = [
        message.payload
        for message in backend.take_outbound_messages()
        if isinstance(message.payload, ValueChange)
    ]

    assert updates[-1].updates == {viewer.playhead_ref.value_key: 0.5}


def test_required_catalog_count_uses_later_animals_as_fallbacks(
    monkeypatch, tmp_path
) -> None:
    xeno_canto = _load_xeno_canto_module()
    searched: list[str] = []

    class FakeQueryBuilder:
        def group(self, _group):
            return self

        def english_name(self, name):
            self.name = name
            return self

        def quality(self, _quality):
            return self

        def build(self):
            return self.name

    class FakeClient:
        def __init__(self, *, api_key):
            assert api_key == "test-key"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def search(self, query, **_kwargs):
            searched.append(query)
            if query == xeno_canto.DEFAULT_ANIMALS[0].english_name:
                return []
            return [
                {
                    "id": str(len(searched)),
                    "en": query,
                    "gen": "Example",
                    "sp": query,
                    "length": "00:01",
                }
            ]

    class FakeDownloader:
        def __init__(self, *, output_dir):
            self.output_dir = output_dir

        def download_recordings(self, _recordings):
            raise AssertionError("cached test recording should not download")

    xcapi = ModuleType("xcapi")
    xcapi.__path__ = []
    client_module = ModuleType("xcapi.client")
    client_module.XenoCantoClient = FakeClient
    downloader_module = ModuleType("xcapi.downloader")
    downloader_module.Downloader = FakeDownloader
    query_module = ModuleType("xcapi.query")
    query_module.QueryBuilder = FakeQueryBuilder
    monkeypatch.setitem(sys.modules, "xcapi", xcapi)
    monkeypatch.setitem(sys.modules, "xcapi.client", client_module)
    monkeypatch.setitem(sys.modules, "xcapi.downloader", downloader_module)
    monkeypatch.setitem(sys.modules, "xcapi.query", query_module)

    cached = tmp_path / "cached.mp3"
    cached.write_bytes(b"cached")
    monkeypatch.setattr(xeno_canto, "_recording_path", lambda *_args: cached)

    def fake_from_file(_path, *, label, metadata, max_duration):
        assert max_duration == 8.0
        return AudioClip(label, np.zeros(16, dtype=np.float32), 16, metadata)

    monkeypatch.setattr(xeno_canto.AudioClip, "from_file", fake_from_file)

    clips = xeno_canto.download_catalog(
        xeno_canto.DEFAULT_ANIMALS,
        cache_dir=tmp_path,
        api_key="test-key",
        required_count=2,
    )

    assert tuple(clips) == ("Common blackbird", "American bullfrog")
    assert searched == [
        animal.english_name for animal in xeno_canto.DEFAULT_ANIMALS[:3]
    ]
