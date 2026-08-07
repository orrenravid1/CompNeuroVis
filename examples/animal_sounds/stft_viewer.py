"""Reusable STFT surface, moving spectrum slice, and audio transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Mapping

import numpy as np
from scipy import signal
from scipy.io import wavfile

from compneurovis.core.runtime.performance import perf_log


TARGET_SAMPLE_RATE = 44_100
DEFAULT_WINDOW_SECONDS = 8.0


def _slug(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in value)
    return cleaned.strip("_").lower() or "stft"


def _float_mono(samples: Any) -> np.ndarray:
    array = np.asarray(samples)
    if array.ndim == 2:
        array = np.mean(array.astype(np.float32), axis=1)
    if array.ndim != 1:
        raise ValueError("Audio samples must be mono or shaped (frames, channels)")
    if np.issubdtype(array.dtype, np.integer):
        limit = max(abs(np.iinfo(array.dtype).min), np.iinfo(array.dtype).max)
        array = array.astype(np.float32) / float(limit)
    else:
        array = array.astype(np.float32)
    return np.nan_to_num(array, copy=False)


def _decode_audio(path: Path, sample_rate: int) -> np.ndarray:
    try:
        import miniaudio
    except ImportError:
        if path.suffix.lower() != ".wav":
            raise RuntimeError(
                "MP3/FLAC decoding needs optional animal-sounds dependencies: "
                "install this app's environment from examples/animal_sounds"
            ) from None
        source_rate, samples = wavfile.read(path)
        mono = _float_mono(samples)
        if source_rate == sample_rate:
            return mono
        divisor = np.gcd(int(source_rate), int(sample_rate))
        return signal.resample_poly(
            mono, sample_rate // divisor, source_rate // divisor
        ).astype(np.float32)

    # Decode memory, not filename. Native Windows path handling in miniaudio
    # can reject valid Xeno-canto names containing decomposed Unicode accents.
    decoded = miniaudio.decode(
        path.read_bytes(),
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
        sample_rate=sample_rate,
    )
    return np.asarray(decoded.samples, dtype=np.float32)


@dataclass(frozen=True, slots=True)
class AudioClip:
    """Decoded mono clip plus display metadata."""

    label: str
    samples: np.ndarray
    sample_rate: int = TARGET_SAMPLE_RATE
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        samples = _float_mono(self.samples)
        if not len(samples):
            raise ValueError("Audio clip cannot be empty")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        sample_rate: int = TARGET_SAMPLE_RATE,
        max_duration: float = DEFAULT_WINDOW_SECONDS,
    ) -> "AudioClip":
        resolved = Path(path).expanduser().resolve()
        samples = _decode_audio(resolved, sample_rate)
        samples = samples[: max(1, round(max_duration * sample_rate))]
        return cls(
            label=label or resolved.stem,
            samples=samples,
            sample_rate=sample_rate,
            metadata={"path": str(resolved), **dict(metadata or {})},
        )


@dataclass(frozen=True, slots=True)
class STFTViewerPanels:
    surface: Any
    spectrum: Any
    controls: Any


class STFTViewer:
    """Composable STFT viewer built from first-party CompNeuroVis widgets.

    Call ``declare(source)`` once, and call ``step(ctx)`` from that source's
    step callback. Several viewers may share one source and one step callback.
    """

    def __init__(
        self,
        clip: AudioClip,
        *,
        name: str = "Audio",
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        n_fft: int = 1024,
        hop_length: int = 384,
        time_display_scale: float = 3.0,
        play_pause_hotkey: str | None = "Space",
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if n_fft < 32 or n_fft % 2:
            raise ValueError("n_fft must be an even integer >= 32")
        if not 0 < hop_length <= n_fft:
            raise ValueError("hop_length must be in [1, n_fft]")
        if clip.sample_rate != TARGET_SAMPLE_RATE:
            raise ValueError(f"AudioClip sample_rate must be {TARGET_SAMPLE_RATE}")
        if not np.isfinite(time_display_scale) or time_display_scale <= 0:
            raise ValueError("time_display_scale must be positive and finite")

        self.name = name
        self._prefix = _slug(name)
        self.window_seconds = float(window_seconds)
        self.n_fft = int(n_fft)
        self.hop_length = int(hop_length)
        self.time_display_scale = float(time_display_scale)
        self.play_pause_hotkey = play_pause_hotkey
        self.clip = clip
        self._spectrogram = np.empty((0, 0), dtype=np.float32)
        self._times = np.empty(0, dtype=np.float32)
        self._frequencies_khz = np.empty(0, dtype=np.float32)
        self._position = 0.0
        self._published_position = -1.0
        self._playing = False
        self._play_started_at = 0.0
        self._play_started_position = 0.0
        self._device = None
        self._stream = None
        self._playhead_ref = None
        self._surface_ref = None
        self._recompute()

    @property
    def spectrogram(self) -> np.ndarray:
        return self._spectrogram

    @property
    def times(self) -> np.ndarray:
        return self._times

    @property
    def frequencies_khz(self) -> np.ndarray:
        return self._frequencies_khz

    @property
    def position(self) -> float:
        if not self._playing:
            return self._position
        elapsed = time.monotonic() - self._play_started_at
        fraction = self._play_started_position + elapsed / self.window_seconds
        return float(np.clip(fraction, 0.0, 1.0))

    @property
    def _end_position(self) -> float:
        return min(self.clip.duration / self.window_seconds, 1.0)

    @property
    def playhead_ref(self):
        return self._playhead_ref

    @property
    def surface_ref(self):
        return self._surface_ref

    def load(self, clip: AudioClip) -> None:
        """Swap clip while preserving field shape and authored panel identity."""
        if clip.sample_rate != TARGET_SAMPLE_RATE:
            raise ValueError(f"AudioClip sample_rate must be {TARGET_SAMPLE_RATE}")
        self._stop_audio()
        self.clip = clip
        self._position = 0.0
        self._published_position = -1.0
        self._recompute()

    def _recompute(self) -> None:
        started = time.monotonic()
        sample_count = round(self.window_seconds * self.clip.sample_rate)
        padded = np.zeros(sample_count, dtype=np.float32)
        usable = min(sample_count, len(self.clip.samples))
        padded[:usable] = self.clip.samples[:usable]
        frequencies, times, values = signal.stft(
            padded,
            fs=self.clip.sample_rate,
            window="hann",
            nperseg=self.n_fft,
            noverlap=self.n_fft - self.hop_length,
            boundary=None,
            padded=False,
        )
        magnitude = np.abs(values).astype(np.float32)
        reference = max(float(np.max(magnitude)), np.finfo(np.float32).eps)
        decibels = np.clip(
            20.0 * np.log10(np.maximum(magnitude / reference, 1e-4)),
            -80.0,
            0.0,
        )
        # SurfacePlot uses field values as literal z coordinates. Mapping the
        # 80 dB display range into [0, 1] keeps height commensurate with time
        # and frequency axes instead of producing an 80-unit vertical tower.
        self._spectrogram = ((decibels + 80.0) / 80.0).astype(np.float32)
        self._times = times.astype(np.float32)
        self._frequencies_khz = (frequencies / 1000.0).astype(np.float32)
        perf_log(
            "stft_viewer",
            "recompute",
            viewer=self.name,
            sample_count=sample_count,
            spectrogram_shape=self._spectrogram.shape,
            spectrogram_bytes=self._spectrogram.nbytes,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    @staticmethod
    def _memory_stream(samples: np.ndarray):
        required_frames = yield b""
        frame = 0
        shaped = samples.reshape((-1, 1))
        while frame < len(shaped):
            end = min(frame + required_frames, len(shaped))
            required_frames = yield shaped[frame:end]
            frame = end

    def _start_audio(self) -> None:
        import miniaudio

        self._stop_audio(update_position=False)
        offset = min(
            len(self.clip.samples),
            round(self._position * self.window_seconds * self.clip.sample_rate),
        )
        self._stream = self._memory_stream(self.clip.samples[offset:])
        next(self._stream)
        self._device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=1,
            sample_rate=self.clip.sample_rate,
            buffersize_msec=40,
            app_name="CompNeuroVis STFT viewer",
        )
        self._device.start(self._stream)

    def _stop_audio(self, *, update_position: bool = True) -> None:
        if update_position and self._playing:
            self._position = self.position
        self._playing = False
        if self._device is not None:
            self._device.stop()
            self._device.close()
        self._device = None
        self._stream = None

    def _set_playhead(self, ctx, value: Any) -> None:
        was_playing = self._playing
        self._stop_audio(update_position=False)
        self._position = float(np.clip(float(value), 0.0, 1.0))
        if was_playing and self._position < self._end_position:
            try:
                self._start_audio()
            except Exception as error:
                ctx.show_status(f"Playback failed: {error}", 5000)
                return
            self._playing = True
            self._play_started_position = self._position
            self._play_started_at = time.monotonic()

    def _toggle_play(self, ctx) -> None:
        if self._playing:
            self._stop_audio()
            ctx.show_status(f"Paused {self.clip.label}", 1500)
            return
        if self._position >= self._end_position:
            self._position = 0.0
        try:
            self._start_audio()
        except Exception as error:
            ctx.show_status(f"Playback failed: {error}", 5000)
            return
        self._playing = True
        self._play_started_position = self._position
        self._play_started_at = time.monotonic()
        ctx.show_status(f"Playing {self.clip.label}", 1500)

    def _reset(self, ctx) -> None:
        self._stop_audio(update_position=False)
        self._position = 0.0
        self._published_position = -1.0
        if self._playhead_ref is not None:
            ctx.set_value(self._playhead_ref, 0.0)

    def declare(self, source) -> STFTViewerPanels:
        controls = source.controls(
            f"{self.name} transport", panel_id=f"{self._prefix}_transport"
        )
        self._playhead_ref = controls.slider(
            f"{self._prefix}_playhead",
            label="Playhead",
            min=0.0,
            max=1.0,
            default=0.0,
            steps=500,
            set=self._set_playhead,
        )
        if self.play_pause_hotkey:
            play_hotkey = controls.hotkey(
                self.play_pause_hotkey,
                fn=self._toggle_play,
            )
            controls.button(
                f"{self._prefix}_play_pause",
                label="Play / pause",
                hotkey=play_hotkey,
            )
        else:
            controls.button(
                f"{self._prefix}_play_pause",
                label="Play / pause",
                fn=self._toggle_play,
            )
        controls.button(f"{self._prefix}_reset", label="Reset", fn=self._reset)

        surface_kwargs = {
            "name": f"{self.name} spectrogram",
            "x": self._times,
            "y": self._frequencies_khz,
            "x_dim": "time",
            "y_dim": "frequency",
            "unit": "normalized magnitude",
            "color_map": "fire",
            "color_limits": (0.0, 1.0),
            "render_axes": True,
            "axis_labels": (
                "Time (s)",
                "Frequency (kHz)",
                "Normalized magnitude",
            ),
            "camera_distance": 28.0,
            "camera_elevation": 34.0,
            "camera_azimuth": -58.0,
            "max_refresh_hz": 15,
            "display_scale": (self.time_display_scale, 1.0, 1.0),
        }
        surface = source.surface(values=self._spectrogram, **surface_kwargs)
        self._surface_ref = surface
        sliced = source.grid_slice(
            f"{self.name} spectrum slice",
            surface=surface,
            axis="x",
            position=self._playhead_ref,
            overlay={
                "color": "#f8f8f2",
                "width": 3.0,
                "alpha": 0.95,
                "display_scale": (self.time_display_scale, 1.0, 1.0),
            },
        )
        spectrum = source.line(
            f"{self.name} spectrum",
            source=sliced,
            x=None,
            x_label="Frequency (kHz)",
            y_label="Normalized magnitude",
            y_min=0.0,
            y_max=1.0,
            color_gradient=(
                (0.00, "#ff1744"),
                (0.18, "#ff6d00"),
                (0.36, "#ffd600"),
                (0.52, "#00e676"),
                (0.68, "#00e5ff"),
                (0.84, "#2979ff"),
                (1.00, "#b388ff"),
            ),
            linewidth=2.5,
            background_color="#111318",
            max_refresh_hz=60,
        )
        return STFTViewerPanels(surface=surface, spectrum=spectrum, controls=controls)

    def step(self, ctx) -> None:
        if not self._playing or self._playhead_ref is None:
            return
        position = self.position
        end_position = self._end_position
        if position >= end_position:
            self._stop_audio(update_position=False)
            position = end_position
            self._position = end_position
        if (
            position >= end_position
            or abs(position - self._published_position) >= 1.0 / 120.0
        ):
            self._published_position = position
            ctx.set_value(self._playhead_ref, position)


__all__ = ["AudioClip", "STFTViewer", "STFTViewerPanels", "TARGET_SAMPLE_RATE"]
