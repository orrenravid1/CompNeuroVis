"""Download Xeno-canto catalog and switch animals from one viewer."""

from __future__ import annotations

import compneurovis as cnv

from stft_viewer import STFTViewer
from xeno_canto import download_catalog


clips = download_catalog()
labels = tuple(clips)
viewer = STFTViewer(clips[labels[0]], name="Animal sound", time_display_scale=5)
source = cnv.source(viewer.step)
panels = viewer.declare(source)


def select_animal(ctx, label):
    viewer.load(clips[str(label)])
    ctx.set_data(viewer.surface_ref, viewer.spectrogram)
    ctx.set_value(viewer.playhead_ref, 0.0)
    metadata = viewer.clip.metadata
    ctx.show_status(
        f"{viewer.clip.label} — {metadata.get('type') or 'sound'}; "
        f"recorded by {metadata.get('rec') or 'unknown'}",
        5000,
    )


panels.controls.dropdown(
    "animal",
    label="Animal",
    options=labels,
    default=labels[0],
    set=select_animal,
)

cnv.layout(((panels.surface, panels.spectrum), (panels.controls,)))
cnv.show(title="Xeno-canto animal sounds")
