# Changelog

This changelog is the canonical human-readable release history for CompNeuroVis.

Use it together with:

- `pyproject.toml` for the package version
- Git tags such as `v0.2.0` for immutable release points
- GitHub Releases for published release notes tied to a tag

## Unreleased

### Changed

- Opened widget, panel-host, control/action, operator, contribution, and Vispy
  renderer authoring so built-ins, adjacent scripts, and installed plugins use the
  same canonical `*Spec` and frontend registration paths.
- Renamed frontend-local typed view data to `*RenderConfig` and the ordinary
  QWidget host to `standalone`; removed the separate `Extension*Spec` taxonomy.
- Reorganized components, inline authoring, simulator sources, and the Vispy
  frontend around explicit ownership boundaries.
- Made repeated simulator morphology widgets selection-safe. NEURON morphology
  widgets now own distinct display/history fields, while Jaxley routes every
  canonical selection independently over its shared voltage data.
- Hardened runtime topology, failure propagation, cooperative shutdown, and
  multiprocessing field delivery; invalid routes fail early and authoritative
  field transitions are no longer silently dropped under queue pressure.
- Made operator graphs explicitly acyclic and recursively resolvable, with
  transitive field/value/patch refresh routing for views and visual contributions.
- Kept notebook support experimental while documenting its remaining special actor
  and placement debt.

### Added

- Added installed point-cloud and app-local gauge conformance fixtures for
  third-party widget authoring.
- Added a published third-party widget authoring guide and narrow repository drift
  checks.

## 0.4.0a1 - 2026-07-14

### Changed

- Rebuilt the primary API around inline sources, explicit opt-in views, typed controls, layouts, and `cnv.show()` integration.
- Unified generic, NEURON, and Jaxley source-level widgets while retaining simulator-native data collection paths.
- Clarified morphology selection, history capture, and reset versus clear behavior across supported workflows.
- Replaced the old documentation and test surfaces with a focused alpha guide, example path, and golden-path validation suite.

### Added

- Added representative generic, widget, NEURON, and Jaxley examples for the
  architecture at that release point.
- Added a trusted-publishing GitHub Actions workflow for tagged PyPI releases.

## 0.3.0 - 2026-05-05

### Changed

- Renamed the live-colored directed graph panel API to `StateGraphViewSpec` and `PANEL_KIND_STATE_GRAPH` for channel-state, finite-state-machine, and other state-transition visualizations.
- Reworked controls around `ControlSpec.value_spec` and optional `ControlPresentationSpec`, replacing the old flat control fields and `XYControlSpec`.

### Added

- Added a GitHub Pages workflow that validates docs on pull requests and deploys the strict MkDocs site from `main`.

### Docs

- Documented the GitHub Pages publishing path and required one-time repo Pages configuration.

## 0.2.0 - 2026-04-11

### Changed

- Refactored the core model around `Field`, `Scene`, typed updates, and optional live/replay `Session`s.
- Consolidated backend-backed workflows around shared builders and a common frontend/session architecture.
- Standardized terminology around `Scene` and `startup_scene(...)` across the docs and current public model.

### Added

- Added a sealed PR-readiness attestation workflow with a final commit receipt under `.compneurovis/pr-readiness/`.
- Added a strict MkDocs + Material + `mkdocstrings` docs site for authored guides plus generated API reference.
- Added packaging metadata validation for Poetry extras, lockfile consistency, and contributor tooling install surfaces.
- Added a named contributor extra so local docs/test tooling can be installed with `pip install -e ".[contrib]"`.

### Docs

- Reworked the README toward a user-first introduction with clearer example entrypoints and contributor guidance.
- Added stricter docs validation for markdown paths, docs vocabulary drift, and docs-site build health.
