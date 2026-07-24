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
- `TraceSampler` -> `SeriesSampler` (clean break; alpha)
- `_TraceHandleBinding` (`handles.py`) -> `_SeriesRefBinding`

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

### Phase 0 — safety net (do first)

`tests/test_alpha.py::test_inline_authoring_builds_one_integrated_app_spec` already
compiles line + bar + surface + slider + button through `_make_backend()` ->
`_build_app_spec_for_backend()`. Gaps: **grid_slice, network2d, morphology** are
untested, and grid_slice + surface are both being touched.

- Add compile-only tests for `grid_slice` and `network2d`, mirroring `_lower()`.
- Add an "every example lowers" smoke (import each simulator-free `examples/**/*.py`
  with `cnv.show` patched).

### Phase 1 — mechanical renames

Pure renames, no behavior change. Update `widgets/__init__.py`, `compneurovis/widgets.py`.

### Phase 2 — split the two defects, move producers

- Split `TraceBinding` -> `SeriesProducer` (`name`, `read`, `x`, `max_samples`) +
  `LineBinding` (the ~20 style fields it was already forwarding).
- Split `SurfaceBinding` -> `SnapshotProducer` (N-dim values/read/coords/`FieldReplace`)
  + `SurfaceBinding` (view + panel + geometry lowering).
- Move all producers into `data_producers.py`.

Fixes a layering violation: `backends/neuron/source.py` and `backends/jaxley/source.py`
import `TraceBinding` from `inline/widgets/line.py` — simulator backends depending on a
line-widget internal. After the move they depend on `data_producers`, which is what they
mean.

### Phase 3 — contracts and `declare`

- `Widget` becomes an ABC with abstract `declare(context)`; all six declarations
  subclass it. `__slots__ = ()` so the `frozen=True, slots=True` dataclasses keep slots.
- `attach` -> `declare`. Every docstring already says "declare"; only the method
  disagrees. Reads as `source.add(w)` -> `w.declare(context)`.
- `WidgetBinding` -> `Binding`, made `@runtime_checkable`.
- Add `Producer`/`FieldProducer` protocols and declare them on all four producers (makes
  the Phase 2 tick collapse type-safe).
- Replace the hand-rolled `getattr(...)` checks in `WidgetAuthoringContext.add` and
  `_widget_contribution` with `isinstance` against the protocols.
- Drop `context.add`/`context.line`/`context.bar` from the widget-facing object (keep
  `source.add`). These are the nesting affordances, and `line`/`bar` are an arbitrary
  privilege besides — no principle picks those two.

### Phase 4 — de-privilege (separate effort, not naming)

- `context.series(...)` alongside `context.data(...)` so any widget can own
  append-semantics data. Today only `line` can, so no third party can author a
  time-series plot.
- Let the widget declare its `PANEL_KIND` instead of `context.view()` hardcoding
  `PANEL_KIND_EXTENSION` — today you cannot author a 3D-panel widget at all.
- Move the property -> refresh-kind map out of
  `refresh_planning._VIEW_VALUE_BINDING_SCHEMA` into something the widget/renderer
  declares. Until then, de-privileging a widget costs it fine-grained refresh.
- Wire live Ref senders (the `MutableRef` mutators the contract reserves).

### Phase 5 — controls panels become ordinary panels

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

---

## 5. Decisions

Settled:

1. `Line`/`LineBinding` (not `LinePlot`); core's `LinePlotViewSpec` stays.
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
