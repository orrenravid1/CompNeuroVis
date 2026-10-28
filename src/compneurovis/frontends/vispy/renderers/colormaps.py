from __future__ import annotations

from functools import lru_cache

import numpy as np
from vispy.color import Color


_RAMP_LOW_COLOR_MIX = 0.2


def _single_color_ramp(color, n: int = 256) -> np.ndarray:
    high = np.asarray(Color(color).rgba, dtype=np.float32)
    low = high.copy()
    low[:3] = 1.0 - _RAMP_LOW_COLOR_MIX * (1.0 - high[:3])
    alpha = np.linspace(low[3], high[3], n, dtype=np.float32)[:, None]
    rgb = np.linspace(low[:3], high[:3], n, dtype=np.float32)
    return np.concatenate([rgb, alpha], axis=1)


def _two_color_ramp(low_color, high_color, n: int = 256) -> np.ndarray:
    return _multi_color_ramp((low_color, high_color), n=n)


def _multi_color_ramp(colors, n: int = 256) -> np.ndarray:
    rgba = np.asarray([Color(color).rgba for color in colors], dtype=np.float32)
    if rgba.shape[0] == 0:
        raise ValueError("At least one color is required for a ramp colormap")
    if rgba.shape[0] == 1:
        return _single_color_ramp(colors[0], n=n)
    ramp_positions = np.linspace(0.0, 1.0, rgba.shape[0], dtype=np.float32)
    sample_positions = np.linspace(0.0, 1.0, n, dtype=np.float32)
    return np.stack(
        [
            np.interp(sample_positions, ramp_positions, rgba[:, channel]).astype(np.float32)
            for channel in range(4)
        ],
        axis=1,
    )


def _sample_matplotlib_colormap(name: str, n: int = 256) -> np.ndarray:
    try:
        from matplotlib import colormaps
    except ImportError as exc:
        raise ValueError(
            f"Matplotlib colormap '{name}' requested via 'mpl:' but matplotlib is not installed"
        ) from exc
    try:
        cmap = colormaps[name]
    except KeyError as exc:
        raise ValueError(f"Unknown matplotlib colormap '{name}'") from exc
    samples = np.asarray(cmap(np.linspace(0.0, 1.0, n, dtype=np.float32)), dtype=np.float32)
    return samples


def _sample_matplotlib_ramp(colors, n: int = 256) -> np.ndarray:
    try:
        from matplotlib.colors import LinearSegmentedColormap
    except ImportError:
        return _multi_color_ramp(colors, n=n)
    cmap = LinearSegmentedColormap.from_list("compneurovis-custom-ramp", list(colors))
    samples = np.asarray(cmap(np.linspace(0.0, 1.0, n, dtype=np.float32)), dtype=np.float32)
    return samples


@lru_cache(maxsize=64)
def _cached_colormap_samples(name: str, n: int = 256) -> np.ndarray:
    raw_name = str(name).strip()
    normalized = raw_name.lower()
    if normalized.startswith("mpl-ramp:"):
        colors = tuple(color.strip() or "#000000" for color in raw_name.split(":")[1:] if color.strip())
        if len(colors) < 2:
            raise ValueError("Matplotlib ramp colormaps require at least two colors after 'mpl-ramp:'")
        return _sample_matplotlib_ramp(colors, n=n)
    if normalized.startswith("mpl:"):
        cmap_name = raw_name.split(":", 1)[1].strip()
        if not cmap_name:
            raise ValueError("Matplotlib colormaps require a name after 'mpl:'")
        return _sample_matplotlib_colormap(cmap_name, n=n)
    if normalized.startswith("ramp:"):
        colors = tuple(color.strip() or "#000000" for color in raw_name.split(":")[1:] if color.strip())
        if not colors:
            raise ValueError("Ramp colormaps require at least one color after 'ramp:'")
        if len(colors) == 1:
            return _single_color_ramp(colors[0], n=n)
        return _multi_color_ramp(colors, n=n)
    x = np.linspace(0.0, 1.0, n, dtype=np.float32)
    if normalized == "grayscale":
        rgb = np.stack([x, x, x], axis=1)
    elif normalized in {"state-fire", "white-fire"}:
        return _multi_color_ramp(("#ffffff", "#ffe45c", "#f18f01", "#8f0500"), n=n)
    elif normalized == "fire":
        rgb = np.stack(
            [
                np.clip(1.5 * x, 0.0, 1.0),
                np.clip(2.0 * x - 0.4, 0.0, 1.0),
                np.clip(4.0 * x - 3.0, 0.0, 1.0),
            ],
            axis=1,
        )
    else:
        rgb = np.empty((n, 3), dtype=np.float32)
        left = x <= 0.5
        right = ~left
        rgb[left, 0] = 2.0 * x[left]
        rgb[left, 1] = 2.0 * x[left]
        rgb[left, 2] = 1.0
        rgb[right, 0] = 1.0
        rgb[right, 1] = 2.0 * (1.0 - x[right])
        rgb[right, 2] = 2.0 * (1.0 - x[right])
    alpha = np.ones((n, 1), dtype=np.float32)
    return np.concatenate([rgb, alpha], axis=1)


def _colormap_samples(name: str, n: int = 256) -> np.ndarray:
    samples = _cached_colormap_samples(str(name), int(n))
    if samples.flags.writeable:
        samples.setflags(write=False)
    return samples
