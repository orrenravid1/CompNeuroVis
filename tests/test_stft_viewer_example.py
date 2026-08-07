from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

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
