"""View and play one local WAV, MP3, or FLAC file."""

from __future__ import annotations

import argparse

import compneurovis as cnv

from stft_viewer import AudioClip, STFTViewer


parser = argparse.ArgumentParser()
parser.add_argument("audio_file")
args = parser.parse_args()

viewer = STFTViewer(AudioClip.from_file(args.audio_file), name="STFT")
source = cnv.source(viewer.step)
panels = viewer.declare(source)

cnv.layout(((panels.surface, panels.spectrum), (panels.controls,)))
cnv.show(title=f"STFT — {viewer.clip.label}")
