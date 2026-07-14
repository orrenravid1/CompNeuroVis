---
title: Getting Started
summary: Install, run one example, and see the shape of the inline authoring API.
---

# Getting Started

The fastest way in: install, run one example, then read the concepts. If you only
want one command, run the static surface — it needs no simulator backend.

## Install

```bash
pip install -e .                 # base
pip install -e ".[neuron]"       # NEURON backend
pip install -e ".[jaxley]"       # Jaxley backend
pip install -e ".[matplotlib]"   # matplotlib colormaps (e.g. mpl:viridis)
pip install -e ".[contrib]"      # docs authoring + PR-readiness tooling
```

Extras combine, e.g. `pip install -e ".[contrib,neuron]"`. The frontend is a local
PyQt6/VisPy desktop app today, so run examples in a normal GUI session.

## First look

```bash
python examples/surface_plot/static_surface_visualizer.py
```

A shaded 3-D sinc surface with live appearance controls, no backend required. For
every other runnable entrypoint — NEURON and Jaxley live sims, replay, the widget
gallery — see the generated **[Example Index](reference/example-index.md)**; it is
produced from the example docstrings, so it never drifts from what's on disk.

## The shape of an app

Authoring is inline: a **source** owns its views, controls, and data; `cnv.layout`
arranges the panels; `cnv.show` renders.

```python
import numpy as np
import compneurovis as cnv

x = y = np.linspace(-3, 3, 120, dtype=np.float32)
X, Y = np.meshgrid(x, y)
Z = np.sinc(np.sqrt(X**2 + Y**2)).astype(np.float32)

src = cnv.source()                                  # a source owns views + controls + data
surface = src.surface("sinc", values=Z, x=x, y=y, color_map="bwr")
cnv.layout(((surface,),))                           # arrange the panels
cnv.show(title="First look")                        # render
```

A live simulator app is the same shape with a backend-specific source — e.g.
`cnv.neuron.source(sections=…)` then `src.morphology(...)`, `src.line(...)`,
`src.control(...)`. The source lowers into the same declarative `AppSpec` as
everything else, and the frontend that renders it is a swappable implementation
detail (VisPy today; the app code doesn't depend on it).

## Where to go next

- **[Example Index](reference/example-index.md)** — all runnable entrypoints.
- **[Concepts](concepts/index.md)** — the durable model: fields, geometry, views,
  layout, and the update model.
- **[Tutorials](tutorials/index.md)** — build an app end to end.
- **[Architecture](architecture/index.md)** and **[Design](architecture/design/index.md)**
  — the runtime model and where the project is headed.

## Local docs

```bash
python -m mkdocs serve            # preview locally
python -m mkdocs build --strict   # strict build (CI parity)
```

Pushes to `main` publish the strict build via GitHub Actions.

## Contributor PR flow

1. Run `python scripts/pr_readiness.py check` while iterating.
2. Commit implementation changes normally.
3. As the last commit before pushing to `main` or opening a PR, run
   `python scripts/pr_readiness.py seal --commit` — it reruns the checks, writes a
   commit-keyed receipt under `.compneurovis/pr-readiness/`, and adds the
   attestation commit.
