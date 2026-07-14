# AGENTS

## Current Authority

CompNeuroVis is in an active pre-1.0 refactor.

- Treat current src/ as implementation authority.
- Use current examples/ to understand intended public usage.
- Use README.md for alpha release scope.
- Do not infer current behavior from older docs, tests, or git history unless the
  user explicitly asks.
- Do not add compatibility layers unless the user explicitly requests them.

## Alpha Public Shape

Normal authoring is source-level:

~~~python
import compneurovis as cnv

src = cnv.source(...)
plot = src.line(...)
src.slider(...)
cnv.layout(((plot,), (src.controls_panel,)))
cnv.show()
~~~

Simulator namespaces use the same API:

- cnv.neuron.source(...)
- cnv.jaxley.source(...)

Views are opt-in. Backend ownership of morphology or data does not imply a panel
must be shown.

## Architecture Boundaries

- Models and simulator objects remain UI-agnostic.
- Sources adapt models into app fragments and interaction bindings.
- cnv.show() integrates source fragments into one app and runtime.
- RunSpec and AppSpec remain canonical low-level constructs for custom systems.
- Field and scoped-reference machinery are internal architecture, not required
  user vocabulary.
- Shared widgets and controls belong in generic inline source code.
- NEURON and Jaxley code should contain only simulator-specific collection,
  stepping, geometry, and optimization behavior.
- Preserve native optimized paths such as NEURON pointer-vector collection.
- Controls must be explicit typed methods such as slider, dropdown, checkbox,
  text, button, and hotkey. Do not restore a generic control escape hatch.
- Morphology selection, display, and history are separate opt-in capabilities.

## Package Map

- src/compneurovis/inline: public source authoring and generic bindings
- src/compneurovis/core: canonical specs, messages, actors, routing, and runtime
- src/compneurovis/backends/neuron: NEURON-specific source and backend behavior
- src/compneurovis/backends/jaxley: Jaxley-specific source and backend behavior
- src/compneurovis/frontends/vispy: desktop and notebook rendering
- src/compneurovis/transports: local transport implementations
- src/compneurovis/_source_runtime.py: source-to-runtime lowering and launch

## Editing

- Read affected source before changing architecture.
- Follow existing patterns where they match current source.
- Keep changes narrow and remove obsolete paths instead of preserving them.
- Preserve unrelated user changes in dirty worktrees.
- Use apply_patch for manual edits.
- Use rg for searches.

## Validation

Golden alpha suite:

~~~bash
python -m pytest -q
~~~

It intentionally covers only:

- supported root imports
- core layout and scoped-reference contracts
- fragment validation
- generic inline authoring
- optional NEURON morphology plus selection trace
- optional Jaxley namespace import

Also run:

~~~bash
python -m compileall -q src examples
poetry check --lock
python -m mkdocs build --strict
poetry build
~~~

Manual GUI release checks:

~~~bash
python examples/custom/sine_wave.py
python examples/widgets/surface.py
python examples/neuron/complete_interface.py
~~~

## Skills

Skills are optional debugging aids. Do not invoke them automatically.

- debug-protocol-dataflow
- debug-rendering
- scratch-exploration

No skill may override current source or explicit user direction.

## Release

Current alpha version: 0.4.0a1.

Notebook, remote, composed-source, and advanced multi-actor paths remain
experimental. Do not make them release blockers unless promoted into supported
scope.
