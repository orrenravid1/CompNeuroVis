---
title: Widget Taxonomy and Uniformity
summary: One authoring path for every widget and a definitive class taxonomy for the inline layer — a decision procedure that assigns each class exactly one category (Spec / Declaration / Ref / Producer / Binding / Interaction) with one contract each, the rename map that brings the two outliers (line, bar) into line, and the phased plan that splits the two Producer+Binding defects and de-privileges the controls panel. The concrete prerequisite slice under Authoring Layer Proposal Part A/B.
status: proposal
date: 2026-07-24
updated: 2026-07-24
---

# Widget Taxonomy and Uniformity

**Status: proposal (for review before implementation).**

Groundwork for [Authoring Layer Proposal](authoring-layer-proposal.md) Part A (open
widget registry) and Part B2 (first-class control panels). Those parts assume every
widget is authored one way and a control panel is "just a widget instance"; this
proposal makes the inline layer's class taxonomy uniform enough for that to be true.

## North Star — one path, not two

**Third-party widget authoring is a first-class goal** (settled). Everything here is sized for
that: the class-based taxonomy with real contracts is justified *because* people outside the
library will author widgets. A lighter function-style model (`@composable`-style functions)
would be more compact, but it throws away the immutable, reusable declaration values,
introspection, and definition-time contracts that first-class extension needs — so classes win.

The shape to hold is a **rich internal taxonomy behind a small external surface**. A third-party
author only ever touches ~5 concepts — `Widget`, `declare`, `Ref`, `context.data` /
`context.series`, `context.view` (+ registering a renderer). `Binding` / `Producer` /
`Interaction` are internal and invisible to them. So: do **not** flatten the six internal
categories; **do** guard the external five.

**The single pass/fail test for the whole effort is Phase 4: does the library end with ONE
authoring + rendering path, or two?** Today a built-in goes
`Declaration → Binding → first-class ViewSpec → native renderer`; a third party goes
`Declaration → context.view → ExtensionViewSpec → registered renderer`. **Two paths means "no
widget privileged" has silently failed** — no amount of clean naming rescues it. **One path,
where a built-in is just "a widget that ships with the library and registers its renderer," is
the prize.** If Phase 4 leaves `ExtensionViewSpec` a second-class citizen beside
`SurfaceViewSpec`, stop and rethink.

This has **two grades, and the terminal one is the point:** *capability parity* — a third party
*can* match a built-in (Phase 4) — is the milestone; *identity* — a built-in *is* a third-party
widget, with no typed `ViewSpec` or `Binding` class left for it (Phase 6) — is the destination.
Parity that still leaves the built-ins running on a privileged path is not done.

Two guardrails so the external surface does not bloat on the way:

1. Phase 4 **collapses** the built-in and extension paths into one; it must not add a parallel path.
2. The refresh schema stays **opt-in with a safe blanket default**. The moment it is mandatory,
   the five-concept surface becomes six+ and legibility is traded for performance nobody asked for.

## Principles

1. **Widgets atomic, apps compose.** One widget = one panel. A "complex widget"
   (e.g. spectrogram = surface + grid_slice + playhead) is composed in the app and
   wrapped in a local user class if reuse is wanted — never a library-level composed
   widget. `WidgetContribution` carries a singular `panel`, and `cnv.layout()` places
   panel handles, so a multi-panel widget structurally cannot say where its panels go.
2. **No widget privileged.** One authoring path for built-in and third-party alike.
   `network2d` already proves the public path (`context.data` + `context.view`)
   suffices; `surface`/`grid_slice`/`line`/`bar`/`morphology` use private hooks and
   first-class `ViewSpec` types they should not need.
3. **One class, one category.** Categories are defined below; overlap is a defect, not
   a variant.
4. **Declarations are bare nouns**, matching the authoring verb (`source.line` -> `Line`).
5. **No global or generic-panel defaults.** Type-specific config and its defaults belong to the
   panel/view type that uses them — never bolted onto the generic `PanelSpec`, and never a global
   frontend constant. *Exemplar of the anti-pattern:* the 3-D camera
   (`camera_distance`/`elevation`/`azimuth`) is a field on `PanelSpec`, so every panel kind
   carries it, and its default is hardcoded three inconsistent ways — `200.0` on `PanelSpec`,
   `30.0` on `Surface`, `200.0` again in `viewport.py`. It belongs to the 3-D view/renderer alone.
6. **Control kinds are extensible too.** A third party can register a new *control* kind (a knob,
   a color picker) the same way it registers a new view kind — controls are not a closed,
   frontend-hardcoded set.

---

## 1. The taxonomy

### Decision procedure

Apply in order. The **first** rule that matches assigns the category.

| # | Question | Category | Suffix |
|---|---|---|---|
| 1 | Frozen record living in `core/`, merged into `AppSpec`? | **Spec** | `*Spec` |
| 2 | Constructed by the app author to express intent, passed to `source.add()`? | **Declaration** | bare noun |
| 3 | Names an artifact the runtime owns, returned to the app author? | **Ref** | `*Ref` |
| 4 | Emits runtime updates on a tick after startup (field messages or value changes)? | **Producer** | `*Producer` |
| 5 | Lowers a declaration into canonical Specs at compile time? | **Binding** | `*Binding` |
| 6 | Lowers an interaction to a spec **and** carries a model accessor fired on user events? | **Interaction** | `*Interaction` |

### The rule that makes it definitive

> **A class belongs to exactly one category. If it satisfies two rules, that is a
> defect to split — not a new category to invent.**

This resolves every "is this a Foo or a Bar?" question without taste. Two classes
violate it today (§3).

### Definitions

- **Spec** — canonical, frozen, serializable, core-owned. The compile *target*.
- **Declaration** — immutable authored value. No generated ids, no runtime state.
  Implements `declare(context) -> Ref`.
- **Ref** — names an artifact the runtime owns, possibly in another process. Frozen,
  carries an id/key. May expose read-only accessors and message-emitting mutators.
  Never holds the artifact. Distinct from **Handle**, reserved for *live, locally held*
  objects with direct behavior (`AppHandle`) — not a widget-layer category.
- **Producer** — owns a reader or values and emits runtime updates *repeatedly, per
  tick*. Scope is deliberately **any runtime update**, not just fields; the emitted
  message is a sub-attribute (field producers emit `FieldReplace`/`FieldAppend`, value
  producers emit `ValueChange`).
- **Binding** — internal, mutable, owns generated ids, lowers one declaration into
  canonical specs once at compile time. Emits a `WidgetContribution`.
- **Interaction** — internal, lowers to a single `ControlSpec`/`ActionSpec` **and**
  carries a model accessor (`get`/`apply`/`fn`) invoked on user events, not on ticks.

`WidgetContribution` is the *return type* of a Binding, not a category member.
Facades/contexts (`WidgetAuthoringContext`, `SourceWidgetAPI`, `InlineApp`), sources
(`InlineSource*`), and runtime coordinators (`SeriesSampler`, `InlineBackend`) sit
outside the table — named for their role, not expected to carry these suffixes.

### Contracts (one per category)

A category without a contract is just a naming convention. Rule of thumb: nominal
(ABC) where third parties author; structural (`@runtime_checkable` Protocol) where the
library implements internally but wants `isinstance` to work.

```python
# widgets/api.py — third parties author these, so nominal
class Widget(ABC, Generic[RefT]):
    __slots__ = ()
    @abstractmethod
    def declare(self, context: WidgetAuthoringContext) -> RefT: ...

# compiler.py — internal, many implementors
@runtime_checkable
class Binding(Protocol):
    def contribution(self, backend: Any = None) -> WidgetContribution: ...

# data_producers.py — no contract exists today
@runtime_checkable
class Producer(Protocol):
    def update(self) -> MessagePayload | None: ...   # None = nothing to emit this tick

@runtime_checkable
class FieldProducer(Producer, Protocol):
    def field_spec(self) -> FieldSpec: ...           # initial declaration

# refs.py — frozen, names something the runtime owns
@runtime_checkable
class Ref(Protocol):
    @property
    def key(self) -> str: ...

@runtime_checkable
class MutableRef(Ref, Protocol):
    def send(self, payload: MessagePayload) -> None: ...

# interactions.py
@runtime_checkable
class Interaction(Protocol):
    def spec(self) -> ControlSpec | ActionSpec: ...
```

`PanelRef` remains the contract for anything `cnv.layout()` accepts.

**Producers currently share nothing** — `ArrayFieldBinding.replace_payload()`,
`TraceBinding._drain_message()`, `SurfaceBinding._replace_message()`, and
`DerivedValueBinding.evaluate()` are four spellings of one idea. This is the biggest
contract gap in the layer. Payoff — `InlineBackend.tick()` today runs three
near-identical loops plus a fourth path:

```python
emit_trace_updates(self, self._traces)
for surface in self._surfaces:
    if surface.read is not None: self.emit_update(surface._replace_message().payload)
for binding in self._fields:
    if binding.read is not None: self.emit_update(binding.replace_payload())
self._emit_derived_values()
```

Under one contract that collapses to:

```python
for producer in self._producers:
    message = producer.update()
    if message is not None:
        self.emit_update(message)
```

(Series sampling stays separate — `SeriesSampler` drives `begin_frame()`/`sample()`
per frame; `update()` drains.)

### Ref vs Handle — the naming, settled

Two tiers, two words:

- **`Ref`** — authoring-time name for something the runtime owns, often in another
  process. Mutation is allowed, but only by *sending messages*.
- **`Handle`** — a live, locally held object you act on directly. `AppHandle` is the
  only one.

Prior art:

- matplotlib/MATLAB "handle" = the *live artist object* (`Line2D`, `Patch`) you mutate
  in process. That is the `AppHandle` tier, not the declaration tier.
- React/Vue `ref` = a mutable box with `.value`. Ours is not that.
- **Akka `ActorRef`** = names an actor owned elsewhere; interaction is message-send
  only. **This is exactly ours** — and the codebase already ships the pattern as
  `RemoteActorRef` (`command()`, `invoke_action()`, `reset()`, with an optional `send`
  callback that raises a clear error when unbound).

Evidence the declaration objects are one category: `bind()` (`handles.py`) treats
`ControlHandle`, `SelectionRef` and `ValueRef` **identically**, lowering all three to
`ValueBindingSpec(key)`. The docstrings already contradict the naming — `SelectionRef`
is documented as *"Handle to morphology selection state"*, `DataHandle` as a
*"reference"*. So `ValueRef`/`SelectionRef` were already correct; the rename runs the
other way — every declaration-time `*Handle` becomes `*Ref`.

**Mutation timing.** A Ref is created at declaration time, before the app exists, so it
has nothing to send to yet. Follow `RemoteActorRef`: carry an optional sender, wired at
launch; raise a clear error if a mutator is called while unbound. Refs are frozen
dataclasses, so attach with `object.__setattr__` — `SurfaceHandle.__init__` already
does exactly this for `_binding`. Define the contract now, implement mutators later;
wiring live senders is Phase 4 and must not block the renames.

---

## 2. Classification

| Class | Category | Action |
|---|---|---|
| `Surface`, `GridSlice`, `Morphology`, `Network2D` | Declaration | ok |
| `LineWidget`, `BarWidget` | Declaration | rename -> `Line`, `Bar` |
| `GridSliceBinding`, `MorphologyBinding` | Binding | ok |
| `LinePlotBinding`, `BarPlotBinding` | Binding | rename -> `LineBinding`, `BarBinding` |
| `SpecWidget` | Binding | rename -> `SpecBinding` (implements `contribution()`) |
| `ArrayFieldBinding` | Producer | rename -> `SnapshotProducer` |
| `DerivedValueBinding` | Producer (value) | rename -> `DerivedValueProducer` |
| `TraceBinding` | **Producer + Binding** | **defect — split** |
| `SurfaceBinding` | **Producer + Binding** | **defect — split** |
| `ControlBinding`, `ActionBinding` | Interaction | rename -> `ControlInteraction`, `ActionInteraction` |
| `ValueRef`, `SelectionRef` | Ref | already correct |
| every declaration-time `*Handle` | Ref | rename `*Handle` -> `*Ref` |
| `AppHandle` | Handle (live, not widget-layer) | unchanged |
| `TraceSampler` | runtime coordinator | rename -> `SeriesSampler` |

### The two defects

Both fuse rules 4 and 5 — they emit a `WidgetContribution` *and* push runtime messages:

- `TraceBinding` — `contribution()` plus `_sample()`/`_drain_message()` (`FieldAppend`).
  Also carries ~20 presentation fields it forwards straight into `LineBinding.style`.
- `SurfaceBinding` — `contribution()` plus `_replace_message()`, driven by
  `InlineBackend.tick()` when `read=` is set.

**Morphology and Bar are the reference pattern**: Declaration + Binding + a *shared*
Producer obtained via `context._declare_field(...)`, three separate objects. The fix
makes line and surface look like morphology.

---

## 3. Rename map

### Declarations (public break — exported from `compneurovis/widgets.py`)
- `LineWidget` -> `Line`
- `BarWidget` -> `Bar`

Core keeps `LinePlotViewSpec` / `PANEL_KIND_LINE_PLOT` — the *view* layer's vocabulary,
not to be dragged into the authoring layer.

### Bindings (internal — no example or test references)
- `LinePlotBinding` -> `LineBinding`
- `BarPlotBinding` -> `BarBinding`
- `SpecWidget` -> `SpecBinding`

### Producers (move to `data_producers.py`)
- `TraceBinding` -> `SeriesProducer` (append / `FieldAppend`)
- `ArrayFieldBinding` -> `SnapshotProducer` (replace / `FieldReplace`)
- `DerivedValueBinding` -> `DerivedValueProducer` (value / `ValueChange`)
- `TraceSampler` -> `SeriesSampler` (clean break; alpha) — also the sampler slot
  `_trace_sampler` -> `_series_sampler`, `ctx.trace_sampler` -> `ctx.series_sampler`,
  `_source_traces` -> `_source_series`, `emit_trace_updates` -> `emit_series_updates`

**Resolved:** `_TraceRefBinding` -> `_SeriesRefBinding` in `refs.py` (the `LineRef` producer
protocol), and the NEURON/Jaxley recording subsystem (#2 above) unified to `series`.

One producer per emitted message, nothing else. The producer extracted from the surface
split emits `FieldReplace` — the *same* contract as `ArrayFieldBinding` — so it is not a
new type but `SnapshotProducer` generalized from one labelled dim to N dims + coords
(rank and coords-in-payload are parameters, not types). No `GridProducer`. This also
exposes that a `Grid`/`Snapshot`/`Series` naming would mix axes — shape vs semantics;
naming producers by emitted message keeps one axis.

### Refs (module `handles.py` -> `refs.py`)

Panels: `PanelHandle` -> `PanelRef`, `SurfaceHandle` -> `SurfaceRef`,
`GridSliceHandle` -> `GridSliceRef`, `LineHandle` -> `LineRef`, `BarHandle` -> `BarRef`,
`MorphologyHandle` -> `MorphologyRef`, `Network2DHandle` -> `Network2DRef`.
Data: `DataHandle` -> `DataRef`.
Controls: `ControlHandle` -> `ControlRef`, and `SliderHandle`, `NumberHandle`,
`DropdownHandle`, `CheckboxHandle`, `TextHandle`, `XYPadHandle`, `ActionHandle` -> `*Ref`.
Already correct: `ValueRef`, `SelectionRef`. Unchanged: `AppHandle` (live tier).

Private structural protocols keep their role but follow the suffix —
`_SurfaceHandleBinding` -> `_SurfaceRefBinding`, etc. They exist so `refs.py` need not
import `widgets/*`: a real circular-import constraint, not sloppiness.

### Interactions
- `ControlBinding` -> `ControlInteraction`
- `ActionBinding` -> `ActionInteraction`

Interaction is a distinct category by the shared-concept check: control/action lowering
shares "compile-time lowering to a spec" with widget bindings, but adds a model accessor
fired on user events that no binding has, and nothing consumes the two polymorphically —
`append_bindings_to_app_spec` iterates `panel_bindings`, `controls`, `actions` in three
separate loops. A shared umbrella type would have no user, so none is invented. Keeping
`*Binding` here would let two categories share a suffix — the exact thing the taxonomy
exists to prevent — hence the rename.

---

## 4. Phases

Each phase is independently shippable and verifiable.

**Status (2026-07-29).** Phases 0–2 **landed** — safety net (incl. a tick-emission harness
covering the runtime path, not just spec lowering), every rename, both producer splits, and
the `trace`→`series` sweep (commits `b4d6f06`…`60684a8`). Phases 3–5 **pending**. The refresh
planner (`refresh_planning.py`) has **not** been touched: it imports only from `core`, so the
authoring-layer refactor could not reach it, and field/view/panel/operator ids plus emitted
message kinds were all preserved (surface keeps coords in its `FieldReplace` via
`replace_includes_coords=True`, so the planner sees the same inputs). It is opened deliberately
in Phase 4.

### Phase 0 — safety net (do first) — **Landed**

`tests/test_alpha.py::test_inline_authoring_builds_one_integrated_app_spec` already
compiles line + bar + surface + slider + button through `_make_backend()` ->
`_build_app_spec_for_backend()`. Gaps: **grid_slice, network2d, morphology** are
untested, and grid_slice + surface are both being touched.

- Add compile-only tests for `grid_slice` and `network2d`, mirroring `_lower()`.
- Add an "every example lowers" smoke (import each simulator-free `examples/**/*.py`
  with `cnv.show` patched).

### Phase 1 — mechanical renames — **Landed**

Pure renames, no behavior change. Update `widgets/__init__.py`, `compneurovis/widgets.py`.

### Phase 2 — split the two defects, move producers — **Landed**

- Split `TraceBinding` -> `SeriesProducer` (`name`, `read`, `x`, `max_samples`) +
  `LineBinding` (the ~20 style fields it was already forwarding).
- Split `SurfaceBinding` -> `SnapshotProducer` (N-dim values/read/coords/`FieldReplace`)
  + `SurfaceBinding` (view + panel + geometry lowering). Surface `read=` now flows through the
  same `_fields` tick path as bar; the special `_surfaces` read loop is gone.
- Move all producers into `data_producers.py`.

Fixes a layering violation: `backends/neuron/source.py` and `backends/jaxley/source.py`
imported `TraceBinding` from `inline/widgets/line.py` — simulator backends depending on a
line-widget internal. They now depend on `data_producers`, which is what they mean.

> **`trace` is overloaded — rename by *idea*, not by blanket search.** Ruling (per "same
> idea → same term"): every use that *is* the series idea becomes `series`; only genuinely
> different concepts stay. Status by concept:
>
> - **#1 inline sampler** (`SeriesSampler`, `_series_sampler`, `ctx.series_sampler`,
>   `_source_series`) — **done** (Phase 2 sweep).
> - **#2 NEURON + Jaxley selected-segment recording** (`_series_refs`/`_series_vector`
>   fast-gather → `_series_history_*` buffer → `_series_field_replace` → the selection line,
>   plus `capture_series` / `should_capture_series_on_click` / `SERIES_FIELD_ID`) — **done**.
>   Its PtrVector implementation is NEURON-specific, but the *idea* is a recorded series over
>   time, so it is unified. The getattr-string protocol in `inline/backend.py`
>   (`_initialize_series_history`, `_series_field_replace`) was kept in sync.
> - **#3 frontend one-curve refresh** (`line_plot.py`: `_refresh_single_trace`,
>   `_apply_single_trace_structure`) — **done** -> `_refresh_single_series` /
>   `_apply_single_series_structure`, matching the file's own `series_dim`/`_series_items`
>   vocabulary. A curve in a line plot *is* a series (Plotly's "trace").
> - **#4 notebook render actor / process** (`_source_runtime.py` / `notebook_host.py`) —
>   **done, internal only.** Confirmed the three-layer split: this is the **render** layer, so
>   it took `line_plot`, not `series` — `NotebookLinePlotRenderActor`, actor id
>   `"line_plot_renderer"`, `line_plot_process`, `_render_line_plot`, `_line_plot_widget/line`,
>   `LINE_PLOT_FRAME_ID`. All routing strings renamed in sync across both files (byte-compiled;
>   **no headless test covers the notebook run — smoke-test a notebook before relying on it**).
>   User-facing follow-through (ruling: nothing the library ships should read `trace` for the
>   line-plot concept): the env vars became `CNV_NOTEBOOK_LINE_PLOT_DPI` / `_QUALITY`, the
>   fallback panel title `"Trace"` -> `"Line plot"`, and the `"notebook_trace"` frame-id value
>   -> `"notebook_line_plot"`. (Panel titles reading "Trace" are fine in a user's own
>   experiment, never in library code or examples.)
> - **Cosmetic** (loop vars `for trace in …`, prose comments, README "trace history", the
>   `selected_trace` example var) — bare-word, left as-is; a light pass, not load-bearing.
>
> Net: **`trace` retires from all shipped identifiers *and* user-facing strings** — `series`
> (data), `line_plot` (view/render). Only freeform prose comments still use the word.

> **Notebook hardcoded-trace fallback removed (opt-in views).** Renaming its title surfaced
> that `NotebookLinePlotRenderActor` *invented* a per-segment line panel (`_fallback_series`
> sampling `segment_display[segment_index]`) whenever no line view was declared — a
> pre-generic vestige that violates "views are opt-in". Removed: the subprocess renderer now
> renders only declared `LinePlotViewSpec`s. Dead for every example (all declare `src.line`),
> so no behavior change for real usage.
>
> **Still open — the in-kernel `NotebookFrontend`.** Its line panel is *entirely* hardcoded
> (`self._buf = segment_display[segment_index]` over time via `_render_line_plot`); it does
> **not** render declared line views at all. That is the same opt-in-views violation, but as
> *primary* behavior rather than a fallback — a real notebook-renderer refactor, untested
> headlessly, deferred to its own effort.

### Phase 3 — contracts and `declare` — **Landed (except Producer protocol, deferred)**

- **Done.** `Widget` is an ABC with abstract `declare(context)`; all six declarations
  subclass `Widget[XRef]` with `__slots__ = ()`, keeping `frozen=True, slots=True`. A missing
  `declare` is now a definition-time error.
- **Done.** `attach` -> `declare` (reads as `source.add(w)` -> `w.declare(context)`).
- **Done.** `WidgetBinding` -> `Binding`, `@runtime_checkable`.
- **Done.** Replaced the hand-rolled `getattr(...)` checks in `source.add` and
  `_widget_contribution` with `isinstance` against `Widget` / `Binding`.
- **Done.** Dropped `context.add` / `context.line` / `context.bar` from the widget-facing
  object; `source.add` invokes `declare` directly. `context` keeps only `data` / `view` (the
  legitimate atomic primitives).
- **Deferred — `Producer` / `FieldProducer` protocols.** These were specified to make the
  "Phase 2 tick collapse" type-safe, but that collapse never happened: `tick()` consumes the
  three producer kinds in three separate loops (`emit_series_updates(self._series)`,
  `for b in self._fields`, `_emit_derived_values()`), and they do **not** share a runtime
  contract — `SeriesProducer`'s two-phase per-frame sampling plus the manual
  `ctx.series_sampler.sample()` feature will not collapse into one post-step `update()` without
  a behavior change. So the protocol would have **no polymorphic consumer** — adding it now is
  speculative abstraction, the exact case decision 7 rejects. Revisit only if a unified tick
  loop is actually built. (A real, smaller wart to fix first: `SeriesProducer` exposes
  `_field_spec` / `_field_id` while `SnapshotProducer` exposes public `field_spec` / `field_id`
  — unify those before any `FieldProducer` protocol.)

### Phase 4 — de-privilege (separate effort, not naming) — **Pending**

**Success criterion (the whole proposal's pass/fail, per the North Star): one authoring +
rendering path.** After Phase 4, "built-in" means only "ships with the library and registers its
renderer" — it confers no capability a third-party widget cannot also declare.

The test is a **capability benchmark, not a deliverable.** `surface` is the most demanding
built-in (3-D panel, N-D coordinate data, operator overlay, surgical refresh), so it is the
ruler: if the public path (`context` data/series + N-D field + `view` + declared panel kind +
registered renderer + optional refresh schema) is powerful enough that surface *could* have been
authored through it, then any genuinely new primitive a third party invents can be too. **Nobody
reimplements surface** — you would just *use* it. If any built-in still needs a private hook or a
first-class `ViewSpec` a third party cannot emit, the phase is not done.

Keep this distinct from **composition**, which is a different axis and needs no Phase 4. An app
like the STFT spectrogram — the existing `surface` fed spectrogram data + `grid_slice` + sliders +
an audio-file dropdown + transport buttons, glued by `cnv.layout` — is *atomic widgets composed at
the app level*. It introduces no new widget and works today. Phase 4 is solely about authoring new
widget **types**, not about composing existing ones into apps.

The levers, each removing one privilege:

- **Done.** `context.series(...)` beside `context.data(...)` — any widget owns
  append-semantics (streaming) data, not just `line`.
- **Done.** `context.grid(...)` — 2-D coordinate-field (surface-class snapshot) data through the
  public path, not a surface-only shape.
- **Done.** `context.view(panel_kind=...)` — a widget declares its panel category instead of
  `context.view` hardcoding `PANEL_KIND_EXTENSION`. And the **core is now fully
  declaration-driven** (the key extensibility fix): every `ViewSpec` carries a `panel_kind`
  (built-ins fixed via `ClassVar`, extensions author-declared), so `_validate_panel` and
  `build_default_layout` check `view.panel_kind == panel.kind` uniformly. The
  `isinstance`-on-view-type ladders are **gone**, and there is no "unsupported panel kind"
  rejection — so a third party's view *and* a novel *panel* kind are first-class, validated by
  the identical rule with zero core knowledge of them. `PANEL_KIND_*` moved to `specs.py` to
  break the views↔app_spec cycle (re-exported from `app_spec` for back-compat). **The authoring
  half of one-path is complete**, proven headlessly: a `Widget` authored only through `context`
  reaches a 2-D field in a native 3-D panel, and a made-up panel kind (`"holographic"`) validates.
- **Pending — the rendering half (GUI-verified).** Frontend render dispatch must route an
  extension view in a 3-D panel to a registered 3-D-capable renderer, and built-in renderers must
  register through the *same* path; plus the refresh-schema registry (below). This is where
  one-path actually converges, and it has **no headless test** — proven only by running a real
  extension widget.
- **Pending.** Wire live Ref senders (the `MutableRef` mutators the contract reserves).

#### Refresh planning: open the schema without taxing authors

**Current state.** `refresh_planning.py` holds five tables keyed by built-in ViewSpec
*type* — `_VIEW_PATCH_SCHEMA`, `_VIEW_VALUE_BINDING_SCHEMA`, `_VIEW_FULL_REFRESH_KINDS`,
`_VIEW_FIELD_ID_PROPS`, plus the operator sets. Each built-in gets surgical targets (surface:
`surface_visual` / `surface_style` / `surface_axes_geometry` / `surface_axes_style` /
`operator_overlay`), but **every `ExtensionViewSpec` collapses to one blanket
`{"extension": None}`** regardless of `kind`. That blanket entry *is* the privilege: a
third-party widget repaints its whole host on any change while a built-in refreshes one target.

**Invariant to preserve** (from [decisions.md](../decisions.md) *Frontend Invalidation*): send
only what the affected targets need. The planner's routing logic — value-key→targets,
field-id→targets, patch-prop→targets — stays exactly as is. **Only the source of a view's
schema changes**: from a hardcoded `type`-keyed dict to a declared, `kind`-keyed lookup.

**Design — a refresh-schema registry**, populated the way renderers already register (the
`extension_renderers.py` entry-point path). The planner resolves a view's schema by:

- built-in view type → its schema (the five tables become the built-ins' *registered* schemas,
  a mechanical extraction with zero behavior change);
- `ExtensionViewSpec` → look up by `view.kind` in the registry;
- nothing registered → today's blanket `{"extension": None}` default.

This is the same move as "widget declares its `PANEL_KIND`": a built-in privilege that lives in
a hardcoded table becomes a declaration the same registry carries. How it meets the three goals:

1. **Performance where it matters.** Nothing regresses — built-in schemas are extracted
   verbatim. An extension `kind` that cares declares a schema and gets the *identical* surgical
   routing; only the lookup key generalizes from `type` to `kind`. A live spectrogram can say "a
   change to `foo` repaints my curve, not my axes."
2. **Authoring stays simple (progressive disclosure).** The schema is **opt-in and lives with
   the renderer**, not the widget declaration. A plain extension widget declares **nothing** and
   gets correct-but-coarse blanket repaint — today's behavior, zero config. Fine-grained refresh
   is a second, optional step, taken only after a measured problem, and declared next to the
   renderer that already knows its own structure (curve vs axes vs legend). The default is safe;
   the sophistication is available, never mandatory — the taxonomy's own "pay for complexity only
   when demanded", applied to refresh.
   - *Named dependency:* surgical refresh needs the extension host to expose partial-refresh
     entry points, since a target kind must map to something repaintable in isolation. Contract:
     the default `ExtensionHost` implements one `refresh(view, inputs, properties)` (blanket, no
     extra work); a host that declares a schema also implements one handler per target kind it
     declares. Opt-in, co-located, only for the widget that needs it.
3. **End user never sees it.** Refresh planning sits entirely below the authoring surface. The
   app author (`cnv.source(...).line(...)`, `cnv.layout(...)`) never touches a schema, a target
   kind, or a host. Their mental model is unchanged: declare widgets, lay them out, run.

**Migration** (each step independently verifiable): (a)+(b) **done** — every view carries a
`kind` (`ClassVar` on built-ins, field on extensions); the four schema tables are re-keyed from
`type(view)` to `view.kind`; the lookups fall back to a blanket default for unregistered kinds;
and `register_view_refresh_schema(kind, …)` lets any kind register a schema (headless test:
built-in surgical refresh preserved, and a third-party kind goes blanket→surgical on register).
(c) **pending, GUI** — the partial-refresh host contract so a registered schema *actually routes*
a partial repaint. Also pending: the `patch`/`full_refresh` schemas already work for any kind,
but `value_binding`/`field_id` use `getattr` (attribute-based, built-in), so extension props
(dict-based `properties`/`inputs`) still route through the `isinstance` branches — those branches,
and the operator/grid-slice special-cases, dissolve in **Phase 6** when built-in views become
properties-based like extensions.

### Phase 5 — controls de-privileged: panels *and* kinds — **Pending**

Two parts. **(a) Control panels become ordinary panels** (below). **(b) Control kinds become
extensible** — today the frontend `controls.py` dispatches `presentation.kind` against a closed
hardcoded set (`slider` / `spinbox` / `dropdown` / `checkbox` / `text` / `xy_pad`), one branch
each, so a third party cannot add a `knob` or `color_picker`. Same fix as views: a **control
renderer registry keyed by presentation kind** (the parallel of the extension-renderer registry),
so a new control kind is registered, not baked in. The built-in typed calls (`src.slider`,
`src.dropdown`, …) stay as app-author sugar, but become thin wrappers over the same
register-a-kind mechanism — no privilege, just convenience. Per [decisions.md](../decisions.md),
the app-author API stays typed (no generic control escape hatch); extensibility is at the
*kind-registration* layer, not a return to untyped control specs. 5b establishes the registry so
third parties *can* register (parity); the built-in controls actually **moving onto it** — the
hardcoded `controls.py` branches deleted so a built-in *is* a registered kind, indistinguishable
from a third-party control — is **Phase 6** (identity), the exact parity→identity split as views.

Implements [Authoring Layer Proposal](authoring-layer-proposal.md) B2. The convergence
there is the key idea: *a control panel is a widget instance*, so "multiple control
panels" is just "multiple instances of one widget kind," exactly like two line plots.
Today the controls panel is the most privileged object in the layer — all four
privileges live in `append_bindings_to_app_spec`:

1. **Hardcoded id** `"controls-panel"` — a magic string in the compiler *and* in
   `source.controls_panel`.
2. **Singleton by kind** — `next(... if panel.kind == PANEL_KIND_CONTROLS)` takes the
   first match, so a second controls panel can never be addressed.
3. **No targeting** — every control and every `show_button` action is forced into that
   one panel, including widget-contributed `WidgetContribution.controls`.
4. **The compiler invents layout** — it appends to `panels` *and* `panel_grid`, actively
   fighting `cnv.layout()`: a grid that omits `controls-panel` fails validation with
   `panel_grid omits panels: controls-panel`.

Target state:

- **The compiler never invents a panel.** Panels come from widgets, uniformly.
- A `Controls` widget (Declaration + `ControlsBinding`, like every other) emits the
  `PanelSpec`.
- `ControlInteraction`/`ActionInteraction` gain a `panel_id`; controls/actions take an
  optional `panel=` targeting a `ControlPanelRef`, `None` meaning the default.
- The *authoring layer* (source), not the compiler, adds one default `Controls` widget
  when controls exist and none was declared. Back-compatible; keeps the compiler pure.
- `source.controls_panel` keeps working as the ref to that default — it just stops being
  the only possible one.

```python
playback = src.control_panel("Playback")        # -> ControlPanelRef, an ordinary panel
src.slider("speed", label="Speed", min=0.25, max=4.0, panel=playback)
src.button("play", label="Play", fn=..., panel=playback)
src.slider("gain", label="Gain", min=0.0, max=2.0)   # -> default control panel

cnv.layout(((surface, section), (playback, src.controls_panel)))
```

Touches `compiler.py`, `sources.py`, and `frontends/vispy/frontend.py` (which resolves
`PANEL_KIND_CONTROLS`). Behavior change, not a rename — out of Phases 0-1.

### Phase 6 — built-ins ARE third-party (widgets *and* controls) — zero discrepancy — **In progress (line_plot landed), terminal**

The North Star's literal end state, made an explicit deliverable: *no discrepancy whatsoever*
between a built-in and a third party — for **views/widgets and controls alike**. Earlier phases
achieve **capability parity** (a third party *can* match a built-in). This one achieves
**identity** (a built-in *is* a third-party — same types, same registry, same path), by removing
every remaining privilege:

1. **Typed first-class `ViewSpec` classes** (`SurfaceViewSpec`, `LinePlotViewSpec`,
   `BarPlotViewSpec`, `MorphologyViewSpec`, `StateGraphViewSpec`) collapse into the one generic
   view (`kind` + `inputs` + `properties`). A built-in's typed config moves into `properties`;
   type-safety is not lost, it is *de-privileged* — the surface renderer parses `properties` into
   a `SurfaceProps` dataclass, and a third-party renderer does the identical thing for its own
   props. Nobody gets a blessed core type.
2. **`Binding` classes** (`SurfaceBinding`, `LineBinding`, …) are deleted; built-in widgets author
   through `context` (`context.grid` + `context.view("surface", …)`) exactly like a third party.
3. **Type-keyed rendering + refresh** in the frontend becomes **kind-keyed** for everyone: every
   renderer — surface's included — registers by `kind` in the one registry (Phase 4's rendering
   half) with its refresh schema declared there.
4. **Type-specific config and defaults come off the generic `PanelSpec`** (principle 5). The 3-D
   camera (`camera_distance`/`elevation`/`azimuth`) stops being a `PanelSpec` field every panel
   kind carries; it moves into the 3-D view's `properties`, its default owned by the surface
   renderer alone (deleting the duplicated `200.0`/`30.0` constants in `PanelSpec`, `Surface`, and
   `viewport.py`). A third-party 3-D widget declares its own camera the same way — no global
   default to inherit.
5. **Built-in controls dissolve onto the control-kind registry** (Phase 5b is the mechanism; this
   is the identity). `controls.py`'s hardcoded `if resolved_kind == "slider"` / `"dropdown"` / …
   branches are **deleted**; the built-in slider/dropdown/checkbox/text/xy-pad renderers register
   by kind in the *same* registry a third-party `knob` uses, and `ControlPresentationSpec`
   collapses to generic `kind` + `properties` (no closed set of blessed kinds). `src.slider` stays
   as typed app-author sugar, but under it a built-in control *is* a registered kind, byte-for-byte
   the same mechanism as a third-party control — the exact parity/identity split as views.

Depends on Phase 4's rendering half (kind-keyed renderer + refresh registry must exist before
built-ins can move onto it), and on Phase 5b (the control-kind registry). Executed one built-in
at a time — view or control.

**Acceptance test, controls edition:** a third-party control kind and a built-in `slider` must
lower and render through the identical path; if `controls.py` still has *any* per-kind branch for
a built-in, or `ControlPresentationSpec` still enumerates blessed kinds, it is not done.

**Acceptance test (brutal, per built-in):** convert the widget to the pure public path and diff.
If any `*ViewSpec` or `*Binding` for it survives, or the frontend still dispatches it by type, it
is not done. Phase 6 completes when those typed specs and binding classes are **deleted** and
`ExtensionViewSpec` is simply *the* view spec. Then "built-in" means only "ships in this repo".

**Landed — `line_plot`, the first kind fully through (items 1 & 3 for it):**

- **All lines emit `ExtensionViewSpec(kind="line_plot")`** — `read=`, `source=`, and grid-slice
  `operator` alike, rendered through the extension registry like any third-party widget. There is
  one representation, so no `as_extension` flag survived — it was deleted, not renamed. `LineBinding`
  no longer emits a typed spec; it remains only as a lowering helper that builds the extension view
  (deleting it in favour of direct `context` authoring is item 2, still open).
- **`LinePlotViewSpec` is emitted as a view nowhere.** It is demoted to a frontend render-config,
  reconstructed inside `LinePlotExtensionHost` from the view's raw `properties`. This *refines
  decision 1*: the type "stays," but only as an internal render struct, not a first-class view —
  exactly the precedent `StateGraphViewSpec` already set (below).
- **Operator = just data.** A grid-slice operator resolves to its computed field at input time
  (`_resolve_extension_input`); the planner expands an operator-valued input to the operator's
  *source field + value keys* generically. The line, its host, and the refresh contract carry zero
  operator-awareness; the old `isinstance(LinePlotViewSpec)` operator/selector/level planner
  branches are deleted.
- **The extension refresh contract carries `values`** (`refresh(view, inputs, properties, values)`),
  so a renderer can resolve bindings nested in structured properties (line's level markers,
  selectors, per-series styling) the same way the native path did. `_contains_binding` also descends
  dataclass fields now, so a control-bound `LevelMarker` in an extension view still triggers refresh
  — generically, with no view-type knowledge.
- **Host hierarchy fixed to base + siblings**, killing reuse-inheritance in both families:
  `GraphHostPanel` → {`StateGraphHostPanel` native, `Network2DHostPanel` extension} and
  `LineHostPanel` → {`LinePlotHostPanel` native, `LinePlotExtensionHost` extension}. The base owns
  the visual + render call; each sibling owns only its spec→render adaptation.
- **Bug fixed in flight:** the extension line's `kind="line_plot"` collided with the *typed*
  line_plot entries still in the kind-keyed schema tables, mis-routing `full_refresh` to a native
  host it no longer has (live lines masked it; static ones would not have rendered). The dead
  `line_plot` view-kind entries were removed; `bar_plot` keeps its own (bars stay typed for now).

**`state_graph` — done (native stack deleted).** Nothing authored `StateGraphViewSpec` — it was
built only inside `Network2DHostPanel` as a render-config, and the `PANEL_KIND_STATE_GRAPH` native
branch was never reached (`Network2D`, an extension widget, *is* the graph authoring surface). So the
entire native state-graph stack was removed: the `PANEL_KIND_STATE_GRAPH` panel branch + its whole
inert refresh pipeline in `frontend.py`, the `StateGraphHostPanel` native host, the `state_graph`
kind-keyed refresh-table entries + `RefreshTarget.state_graph`, and the `PANEL_KIND_STATE_GRAPH`
constant. `StateGraphViewSpec` stays as a pure render-config (no `panel_kind`/`kind`) built by
`Network2DHostPanel`, and `GraphHostPanel` was folded into `Network2DHostPanel` (the base existed to
host two siblings; with the native one gone the visual has a single consumer). Verified: full suite +
network2d GUI smoke. Confirmed dead across framework, examples, tests, *and* the pharynx user model
before deleting (its `state_graph` strings were stale perf-log output, not source).

**`bar_plot` — done (native line/bar rendering fully retired).** Bars reused the line-plot host, so
they were the last thing keeping `"line_plot"` alive in the planner (the `bar_plot`→`line_plot`
tables + `RefreshTarget.line_plot`). Bars now emit `ExtensionViewSpec(kind="bar_plot")` and render
through a `BarPlotExtensionHost` (a sibling of `LinePlotExtensionHost` over the shared `LinePlotPanel`
visual). With line *and* bar both extension, the **entire native line/bar pipeline was deleted**: the
`PANEL_KIND_LINE_PLOT`/`BAR_PLOT` panel branch, the whole `_refresh_line_plot*` pipeline in
`frontend.py` (methods, dirty sets, refresh-loop routing/flush/counters, `force_line_plots`,
constants), the native `LinePlotHostPanel`, `RefreshTarget.line_plot`, and every `line_plot`/`bar_plot`
entry in the planner tables — **the refresh planner now contains zero `line_plot`/`bar_plot` strings.**
`LinePlotViewSpec`/`BarPlotViewSpec` are demoted to render-configs (no `panel_kind`/`kind`), built by
their extension hosts. `LineHostPanel` stays a base (two real siblings now). `src.bar(...)` keeps its
named public-API surface. Verified: 32 tests + GUI smoke (bar/line/surface/network2d).

**Milestone:** three built-in view kinds (`line_plot`, `state_graph`, `bar_plot`) are now extension
widgets; the native typed-view rendering path survives only for `surface`/`morphology` (3-D).

**Still need to do:**
Generic refs — drop per-widget Ref types (Network2DRef, …) for a generic handle.

Generic planner — a widget registers its full refresh behavior (not just the kind tables register_view_refresh_schema already covers, but the operator-dep / overlay / level logic now hardcoded as isinstance), so zero per-widget strings remain in the planner.

---

## 5. Decisions

Settled:

1. `Line`/`LineBinding` (not `LinePlot`). `LinePlotViewSpec` stays in core but is **demoted to a
   frontend render-config** — lines now emit `ExtensionViewSpec(kind="line_plot")`, and the type is
   only reconstructed inside `LinePlotExtensionHost` (see Phase 6 "Landed"). It is emitted as a view
   nowhere.
2. `Widget` as an ABC (nominal), `Binding`/`Producer`/`Ref`/`Interaction` as
   `@runtime_checkable` Protocols. The ABC is for the surface third parties author; it
   does not conflict with the "inline = no inheritance" stance, which is about user
   *models*, not library extension points.
3. `DerivedValueBinding` -> `DerivedValueProducer` — Producer scope is *any* runtime
   update, with field-vs-value as a sub-attribute.
4. `TraceSampler` -> `SeriesSampler`, clean break given alpha (no compat alias — matches
   the [Architectural Automation decision](../decisions.md): immediate convergence over
   aliases).
5. `Ref` for declarations, `Handle` reserved for live objects (`AppHandle`).
6. No `GridProducer` — dissolved by "one producer per emitted message."
7. `Interaction` is a distinct category; `ControlBinding`/`ActionBinding` ->
   `ControlInteraction`/`ActionInteraction`.

### Related asymmetry (noted, not scheduled)

Widgets split Declaration (public, frozen) from Binding (internal, id-bearing). Controls
do **not** — `ControlBinding` is created directly inside `source.slider(...)` and fuses
both roles. Worth deciding later whether controls get the same split; orthogonal to this
refactor and entangled with the "controls are app-level, not widgets" principle and B2.
