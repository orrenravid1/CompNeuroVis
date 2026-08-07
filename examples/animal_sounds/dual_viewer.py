"""Two independent STFT viewers sharing one stable source/runtime."""

from __future__ import annotations

import compneurovis as cnv

from stft_viewer import STFTViewer
from xeno_canto import DEFAULT_ANIMALS, download_catalog


clips = download_catalog(DEFAULT_ANIMALS, required_count=2)
first_clip, second_clip = tuple(clips.values())
left = STFTViewer(first_clip, name="Animal A")
right = STFTViewer(second_clip, name="Animal B")


def step(ctx):
    left.step(ctx)
    right.step(ctx)


source = cnv.source(step)
left_panels = left.declare(source)
right_panels = right.declare(source)

cnv.layout(
    (
        (left_panels.surface, left_panels.spectrum),
        (left_panels.controls,),
        (right_panels.surface, right_panels.spectrum),
        (right_panels.controls,),
    )
)
cnv.show(title="Two animal sounds")
