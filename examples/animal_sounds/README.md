# Animal-sound STFT viewer

`stft_viewer.py` is generic. It composes first-party `surface`, `grid_slice`,
`line`, `slider`, and `button` APIs. `xeno_canto.py` is animal-data adapter.
Loading an animal uses `ctx.set_data(surface, spectrogram)` to emit one new STFT
snapshot. Ordinary playback sends only playhead value changes; continuously
animated surfaces can still use the ordinary `read=` authoring path.

Each STFT viewer composes a Space hotkey object into its play/pause button. Pass
`play_pause_hotkey=None` when embedding a viewer that should not own a shortcut.
In dual mode Space toggles both viewers, while their buttons remain independent.

This is a separate app project. Root CompNeuroVis dependencies stay unchanged.
Create app-local `.venv` and install CompNeuroVis editable plus app dependencies:

```powershell
cd examples/animal_sounds
$env:POETRY_VIRTUALENVS_IN_PROJECT = "true"
poetry install
```

View local recording:

```powershell
poetry run python local_file.py recording.wav
```

Xeno-canto key is read from Git-ignored local `.env`. Then run:

```powershell
poetry run python animal_browser.py
poetry run python dual_viewer.py
```

Browser downloads one short quality-A recording per configured animal into
`.animal_sound_cache/`. Recording metadata stays on each `AudioClip` and appears
in app status bar when selection changes.

Two viewers use one `cnv.source(step)`. This avoids experimental multi-source
composition while keeping transport and panel state independent. Dual mode
tries later configured animals when an earlier query cannot produce a usable
recording, and opens after two clips have loaded.

Performance capture:

```powershell
$env:COMPNV_PERF_LOG = ".perf-logs"
poetry run python animal_browser.py
Remove-Item Env:COMPNV_PERF_LOG
```

Logs are per-process JSONL files. Useful events: `inline_backend/tick_window`
for snapshot rate and MiB/s, `actor_host/step_window` for receive/tick/flush
phase cost, `transport/send` for blocked large sends, and frontend/render events
for projection and GPU refresh cost.
