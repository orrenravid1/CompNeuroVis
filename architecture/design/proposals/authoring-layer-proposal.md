---
title: Authoring Layer Proposal — Widgets, Controls, Distribution, Frontend, Testability
summary: Make authoring easy across the whole surface — an open widget registry; per-type control calls, first-class control panels, dependent/runtime-mutable controls, and authoritative defaults; straightforward distributed/cross-seam authoring over fragments; the frontend as a swappable protocol; explicit logging/config instead of environment variables; and a headless drive API so any of it can be regression-tested. The concrete how under the design-directions through-line.
status: proposal
date: 2026-07-11
updated: 2026-07-13
---

# Authoring Layer Proposal — Widgets and Controls

**Status: proposal (for review before implementation).**

## Thesis

The inline/source layer lowers cleanly *into* `AppSpec` — that half of the
authoring story is done. The gap is *extending* it. Adding a new widget kind, or
declaring a specific control, is high-friction not because the machinery is
missing but because it is **closed and hand-copied**: the spec layer already
supports what an author wants, but the authoring surface makes them either edit
eight framework files (widgets) or construct two spec objects and accept a single
implicit panel (controls).

The goal: **authoring a widget or a control should be as easy as using one.** This
is [Design Directions §1](../design-directions.md) (the open panel/view registry)
and [§6](../design-directions.md) (the authoring tier), reframed around day-to-day
ergonomics. The two parts converge — a controls panel turns out to be just an
instance of a registered widget kind — so they belong in one proposal.

This proposal is the concrete *how* under the
[through-line](../design-directions.md) (one mutable handle model over the message
protocol): every widget kind (Part A) is what a handle instantiates; every control
and panel (Part B) is a handle whose properties are settable — including *at runtime*
(B3) — lowering to the patch protocol; distribution (Part C) is those handles
surviving a seam; the frontend (Part D) is what the mutations serialize to; and Part
F is how any of it is verified headless. Read Parts A–F as the through-line made
buildable.

---

# Part A — Widget authoring layer

## What it takes today

Adding one widget kind touches **10 files**. Tracing `state_graph` (a recent
addition): 65 lines in `frontends/vispy/frontend.py` alone, plus
`refresh_planning.py`, `core/views.py`, `core/app_spec.py`, `inline/bindings.py`,
`inline/sources.py`, `backends/neuron/inline.py`, and two `__init__.py` exports.

The frontend cost is a **template copied per widget**. Every kind gets its own
hand-written parallel family:

- import `{Kind}ViewSpec` + `{Kind}HostPanel` + `{Kind}Panel`
- four instance collections in `__init__`: `{kind}_host_panels`, `{kind}_panels`,
  `_dirty_{kind}_views`, `_{kind}_last_refresh_s`
- clearing those four on reset
- a `force_{kind}=True` in the full-refresh path
- host-panel construction in `_rebuild_panels`, keyed by panel kind
- `_{kind}_view()` + `isinstance`, `_{kind}_refresh_interval_s()`,
  `_refresh_{kind}_if_due()` (the ~40-line one: deadline → interval → dirty →
  fetch fields → `host.refresh`), and `_flush_due_{kind}_refreshes()`

Plus, per widget: a `PANEL_KIND_*` constant + concrete import + `isinstance`
validation + default-layout mapping in `core/app_spec.py`, a schema entry + a
`RefreshTarget` classmethod + routing branches in `refresh_planning.py`, a
`*Widget` builder in `inline/bindings.py`, and a `src.foo(...)` method in
`inline/sources.py`. Boilerplate-to-substance is roughly **5:1**, spread across
layers a widget author should never have to touch (core validation, the frontend
scheduler).

## Substance vs. mechanism

Only three pieces are genuinely widget-specific — what an author *should* write:

1. a **`ViewSpec`** — its data-field contract and style props;
2. a **renderer/panel** — draw it, given `(view, fields, values)`;
3. a thin **authoring method** — `src.bar(...)` producing the view + its data field.

Everything else (~150 lines across 8 files) is registration and dispatch that
should be *derived from a registration*, not hand-copied.

## Two of the three seams already exist

The design is not from scratch:

- **App-spec assembly is already uniform.** `SpecWidget` / `LinePlotWidget` /
  `BarPlotWidget` / `StateGraphWidget` all expose one
  `contribution(backend) -> PanelContribution(fields, views, panel, controls)`. The
  app-spec compiler already treats widgets generically.
- **Refresh *routing* is already table-driven.** `refresh_planning.py` keys off
  dicts (`_VIEW_FIELD_ID_PROPS`, `_VIEW_VALUE_BINDING_SCHEMA`,
  `_VIEW_FULL_REFRESH_KINDS`) per `ViewSpec` type — it just isn't open for
  registration.
- **The frontend dispatch is the one part still hand-copied** — the N parallel
  `{kind}_*` families in `frontend.py`.

## Proposed contract

A **widget registration** closes the loop — one object per kind:

```python
# illustrative
@dataclass(frozen=True)
class WidgetKind:
    kind: str                         # panel kind id, e.g. "bar_plot"
    view_spec_type: type[ViewSpec]    # the declarative schema
    field_id_props: tuple[str, ...]   # attrs naming data fields (for field-replace routing)
    value_binding_props: tuple[str, ...]  # attrs that may carry ValueBindingSpec (for value routing)
    build_panel: Callable[[HostContext], WidgetPanel]     # renderer factory
    # panel.refresh(view, fields: Mapping[str, Field], values: dict) -> None  (uniform)
    default_max_refresh_hz: float | None = None

def register_widget(kind: WidgetKind) -> None: ...
```

The renderer implements one uniform method — `refresh(view, fields, values)` —
instead of each widget inventing its own host-panel signature
(`refresh(view, node_field, edge_field, values)` etc.). The `fields` mapping is
resolved by the dispatcher from `field_id_props`, so the renderer never fetches
fields itself.

## Generic dispatcher

The frontend keeps **one** `dict[kind, WidgetRuntime]` and iterates it. Each
`WidgetRuntime` owns what today is a hand-written family: its host-panel map,
dirty set, last-refresh map, `refresh_if_due`, and flush loop — parameterized by
the registration's `build_panel`, `field_id_props`, and refresh policy. The `N`
copied families collapse to one generic implementation.

`core/app_spec.py` validates a panel's kind against the **registry**, not an
`isinstance` ladder. `refresh_planning.py` reads `field_id_props` /
`value_binding_props` from the registration instead of the hardcoded
`_VIEW_*` dicts.

## What an author writes (after)

```python
# a new connectivity widget — three substantive pieces, one registration
class GraphViewSpec(ViewSpec): ...            # 1. schema
class GraphPanel(WidgetPanel):                # 2. renderer
    def refresh(self, view, fields, values): ...
register_widget(WidgetKind(                   # 3. wire-up (replaces ~150 lines)
    kind="graph",
    view_spec_type=GraphViewSpec,
    field_id_props=("node_field_id", "edge_field_id"),
    value_binding_props=("node_color_map", "node_size", ...),
    build_panel=GraphPanel,
))
# and a thin src.graph(...) authoring method (or a generic src.widget("graph", ...))
```

No edits to `frontend.py`, `app_spec.py`, or `refresh_planning.py`.

## Migration and escape hatches

- The five existing widgets (morphology, line_plot, bar_plot, state_graph,
  surface) become registrations; their renderers gain the uniform `refresh`
  signature. This is a mechanical refactor, verifiable against the golden
  behavior fingerprints.
- **Morphology keeps its escape hatch.** It has entity picking and camera/host
  concerns beyond `refresh(view, fields, values)`. The registration allows an
  optional richer host contract (selection, camera) for kinds that need it, so the
  common case stays trivial while morphology-class widgets remain expressible.
- Built-in kinds and third-party/registered kinds go through the same path — no
  privileged core set.

---

# Part B — Control authoring

## B1 — Per-type control calls

**Problem.** To make a control today you call the generic
`src.control(name, *, label, get, set, min, max, default, value_spec, presentation,
send_to_backend)` and must know the **(value_spec, presentation) pairing**:

```python
# a slider — two spec objects, and you must know they pair
src.control("gain", label="Gain",
            value_spec=cnv.ScalarValueSpec(default=0.5, min=0, max=1),
            presentation=cnv.ControlPresentationSpec(kind="slider", steps=100))
# a dropdown — different value spec, different presentation kind
src.control("cmap", label="Colormap",
            value_spec=cnv.ChoiceValueSpec(default="fire", options=(...)),
            presentation=cnv.ControlPresentationSpec(kind="dropdown"))
```

Nothing tells you what a slider *needs*; you learn the pairing by reading source.
There are exactly six shapes (float slider, int spinbox, checkbox, dropdown, text,
xy-pad), each a fixed value-spec × presentation combination.

**Proposal.** Add one thin call per control type, mirroring matplotlib widgets /
ipywidgets / Streamlit (`st.slider`, `st.selectbox`, `st.checkbox`):

```python
src.slider("gain", min=0, max=1, default=0.5, steps=100, scale="linear", label="Gain")
src.number("nseg", min=1, max=64, default=8, int=True, label="Segments")   # spinbox
src.dropdown("cmap", options=("fire","bwr"), default="fire", label="Colormap")
src.checkbox("autostep", default=True, label="Auto-step")
src.text("preset", default="", placeholder="preset name", label="Preset")
src.xy_pad("conductances", x=("g_Na", 0, 1), y=("g_K", 0, 1), label="Conductances")
```

Each is a **wrapper** that constructs the correct `value_spec` + `presentation` and
calls the existing `control(...)` — no new core machinery. Appearance is per-type
kwargs where it makes sense (`steps`, `scale` for sliders; `int` for number;
columns later). `get=`/`set=` remain optional exactly as today (a control with
neither just holds its value). **`src.control(...)` stays** as the generic escape
hatch for a custom `value_spec`/`presentation`, so nothing is lost.

This also lets a control's *appearance* be specified inline without a second
object — the request in the prompt — because the presentation options become named
kwargs of the typed call.

**Three papercuts to fold in while here** (all observed writing ~29 controls by hand
across the two ligand explorations):

- **A `bind` helper for the common case.** Nearly every control is the same shape:
  `get=lambda: obj.attr, set=lambda ctx, v: setattr(obj, "attr", float(v))`. Add
  `src.slider("g_Na", bind=(cell, "gnabar"), min=…, max=…)` (or a standalone
  `src.bind(obj, "attr")`) that synthesizes both callbacks. It erases the bulk of the
  boilerplate and removes the easiest place to typo an attribute name.
- **`get`/`set` asymmetry.** `get` is arg-free (`lambda:`) while `set` takes
  `(ctx, v)`. Minor, but it's a re-checked-every-time papercut; the typed calls are
  the place to make the callback shapes consistent (or hide them behind `bind`).
- **`send_to_backend` leaks the seam.** Passing a `set` callback silently flips
  `send_to_backend` to `True`. It works, but "backend" is a concept an inline author
  shouldn't reason about; the typed calls should not surface it at all (routing is an
  implementation detail of where the `set` runs — the sampler-locus point from the
  [through-line](../design-directions.md)).

## B2 — First-class control panels

**Problem.** There is exactly one implicit controls panel. `src.controls_panel`
returns a fixed `PanelHandle("controls-panel")`, and the app-spec compiler
(`inline/bindings.py`) collects **every** source control id and dumps it into that
one panel. You cannot group controls, route a control to a specific panel, or have
two control panels — even though the spec layer already supports
`PanelSpec(kind="controls", control_ids=subset)` and multiple such panels.

**Proposal.** Make a control panel a created object controls attach to:

```python
params = src.control_panel("Channel parameters")     # returns a ControlPanelHandle
stim   = src.control_panel("Stimulus")

params.slider("g_Na", min=0, max=1, default=0.12)     # panel-scoped authoring
params.slider("g_K",  min=0, max=1, default=0.036)
stim.slider("amp", min=0, max=2, default=1.0)
stim.checkbox("enabled", default=True)

cnv.layout(((morph, volt), (params, stim)))           # each panel placed like any handle
```

Equivalent flat form for one-offs: `src.slider(..., panel=params)`. **Back-compat:
if no panel is created, today's behavior is preserved** — controls declared with
bare `src.slider(...)` / `src.control(...)` collect into the single default
`controls-panel`, and `src.controls_panel` keeps working. Per-panel appearance
(column policy `single_column` / `auto_columns` / fixed-n, later collapsible
sections) lives on `control_panel(...)`, resolving the controls-density backlog
item too.

## B3 — Dependent / dynamic controls (re-spec at runtime)

**Problem.** A control's *spec* — its options, range, label, default — often depends
on another control's value, and today the inline layer cannot express that. Concrete
case, from `hh_competing_ligand_parameter_modulation_exploration.py`: a dropdown
selects which downstream HH parameter the effector modulates, and the modulation-gain
slider should re-range per target (gNa wants ±0.12, EL wants ±25 mV). The original
`BufferedSession` version did this by emitting the legacy
`ScenePatch(control_updates={…})` + `StatePatch` god-patch from the dropdown handler.
The inline control layer has **no** surface for it — controls are static bindings — so
the rewrite had to collapse the gain into a single dimensionless "modulation strength
× per-target gain." That's a defensible design, but it was *forced by a capability
gap*, not chosen freely.

**Proposal.** Control handles are mutable, like every other handle in the
[through-line](../design-directions.md). A control's `set` callback (or a declared
`depends_on=`) can re-spec another control:

```python
target = src.dropdown("mod_target", options=PARAM_KEYS, default="el")
gain   = src.slider("mod_gain", **gain_range_for("el"))

@target.on_change
def _(ctx, key):
    gain.reconfigure(**gain_range_for(key))   # -> ControlPatch(gain_id, {...}) [+ ValueChange]
```

**The mechanism already exists in the *core* message layer — and cleanly.** The
refactor already broke the legacy `ScenePatch` god-patch (value + spec + scene, one
message) into a uniform, id-keyed, per-declaration patch family, all live and applied
in the frontend (`app_projection.replace_control(...)` etc.):

- **value** → `ValueChange(updates)` — the control's live value;
- **spec** → `ControlPatch(control_id, updates)` — a *peer* of `ViewPatch` /
  `OperatorPatch`, so a control's spec is patched exactly like a view's; controls are
  **not** privileged in the protocol;
- **placement / structure** → `PanelPatch(panel_id, control_ids|view_ids|…)` /
  `LayoutReplace` — which panel holds which ids; there is no controls-only structural
  message, so "multiple control panels" (B2) needs nothing new here.

So `reconfigure(...)` lowers to a `ControlPatch` (spec) plus a `ValueChange` when the
value snaps to the new default — two uniform members, never a bundled or
control-special patch. B3 is only the *authoring surface* over `ControlPatch`; there
is nothing to add to the messaging layer.

> **Messaging-layer invariant (don't rot it).** Authoring sugar — here and everywhere
> in this proposal — lowers onto the existing uniform members (`ValueChange` /
> `ControlPatch` / `ViewPatch` / `OperatorPatch` / `PanelPatch` / `LayoutReplace`). It
> must **never** resurrect a bundled or kind-privileged patch. The legacy `ScenePatch`
> was exactly that bundling; splitting it was a refactor win, and B3 consumes the
> split pieces rather than undoing them.

**The one real design choice** is the value/spec boundary: how much of a control's
spec (`min` / `max` / `options` / `default`) should be a **bindable value**
(`ValueBindingSpec`, the way view *style* props already resolve through `bind(value)`)
rather than a `ControlPatch` payload. If those props are bindable, a dependent
control's range change becomes a plain `ValueChange` and `ControlPatch` shrinks to
genuinely-structural respec (changing the presentation *kind*). That is the most
uniform, most §2-consistent form ("everything is a value/binding"); `ControlPatch`
covers B3 today either way. Decide this boundary before B3 is built.

This is B1/B2's static control authoring made dynamic, and the first place the
handle-mutation model earns its keep in day-to-day use.

## B4 — Defaults are authoritative

**Problem.** A declared control `default=` is **not** applied to the model at init; the
model keeps whatever value it was constructed with, and the two silently diverge. This
cost real debugging time in `hh_competing_ligand_effector_chain_exploration.py`: the
`SetpointRelaxEffector` mechanism's built-in `tau_on = 5000 ms` overrode the
exploration's intended `12 ms`, so the downstream neuron never fired — caught only
because the spikes were missing, not by any error. The current workaround, in every
inline file, is a hand-written loop that calls each control's `set` fn with its default
to push the declared values into the model before the run starts.

**Proposal.** Declaring `default=` makes the UI default **authoritative** — applied to
the model on init through the same `set` path — either always, or via an opt-in
(`src.apply_defaults()` once, or `apply_default=True` per control). This removes the
boilerplate loop and closes a silent-divergence footgun where "the value the slider
shows" and "the value the model holds at t=0" are unrelated. It is small, and it pairs
naturally with `bind` (B1): a bound control with a default both reads *and seeds* the
attribute.

## The convergence: a control panel is a widget instance

Parts A and B are the same mechanism. Once widgets are a **registry of kinds with
instances placed in layout**, a controls panel is simply an instance of the
registered `controls` widget kind. "Multiple control panels" then falls out for
free — it is "multiple instances of one widget kind," exactly like having two line
plots. `control_panel(...)` becomes the authoring call that creates a `controls`
widget instance; the per-type control calls (B1) target a specific instance (or
the default one). So B2 is *enabled by* A's registry, and the two ship naturally
together.

---

# Part C — Distributed authoring and fragments

The authoring layer must read straightforwardly when sources live on different
sides of a transport seam. Most of the machinery already exists; what's missing is
the authoring surface over it and one settled rule for what a fragment *is*.

## C1 — What a fragment is (the reconciliation)

**A fragment is the actor / source / namespace boundary — the unit of composition
and remoteness. It is never a within-app grouping tool.** Grounded in the current
code:

- Every source becomes one `FragmentScopedBackendActor`: a peer that tags its
  outbound messages with its `fragment_id` and ignores inbound messages tagged for
  other fragments. **One source = one fragment = one actor = one namespace.**
- A single-source app uses `DEFAULT_FRAGMENT_ID` — fragments are *transparent*
  (bare panel/field/control ids, no prefix). You never think about fragments until
  there's more than one actor.
- `build_integrated_app_spec(fragments)` is the composed app spec: fragment
  catalogs stay **local**, layout is the **only** global structure, and panel ids
  get `fragment_id:` prefixes so composed sources can't collide. It is owned by the
  composer/orchestrator — which resolves the `ComposedSource` stub's *"no source is
  privileged to provide the composed AppSpec"*: none is; the *integrator* provides it.
- The bus routes by `fragment_id` tag (`MessageMatch(tags={"fragment_id": …})`), so
  a frontend control change reaches the owning source's actor.

The load-bearing distinction:

| Boundary | Is a fragment? | Example |
|---|---|---|
| A distinct source / actor / data producer | **Yes** | neural sim; physics sim; a remote backend |
| A piece across a transport seam | **Yes** | a `serve`d backend in WSL |
| Panel grouping *within* one source | **No** | two control panels, three line plots, a morphology + its trace — all one fragment |

So the earlier "multiple control panels" request (Part B2) is explicitly **not**
fragmentation — those panels share the source's single fragment. Composing neural +
physics **is** two fragments. Conflating the two is the trap to avoid.

**`CompositeBackendActor` is a hosting detail, not composition.** It co-locates N
fragment actors behind one channel in the script-rerun case (its own docstring says
so). It owns no composition semantics, and in the distributed case it is absent —
each fragment gets its own transport channel and is a plain peer on the bus. There
is **no `ComposedBackend`**, and there should not be: backends communicate as peers
at the bus layer, and the app spec is the integrator's merge of fragments.

## C2 — Authoring across the seam: `show` vs `serve`

There is exactly **one Bus per app run**, so someone must own the routing fabric
and the integrated app spec. That asymmetry is inherent; the authoring surface makes
it a one-word difference:

- **`cnv.show()`** = "I own this app." Orchestrator: starts the bus, integrates all
  fragments (local + remote) via `build_integrated_app_spec`, owns layout, and — if
  it is a frontend — renders.
- **`cnv.serve(actor_id, transport=…)`** = "I contribute a fragment to a remote
  app." Dials into a remote bus, contributes its fragment (fields/views/controls),
  owns no layout or composition.
- **`cnv.remote(actor_id, transport=…)`** references a `serve`d fragment and exposes
  **proxy handles** for the panels it contributes, so the orchestrator can lay them
  out before the connection resolves.

**Asymmetric case** — NEURON backend in WSL, VisPy frontend on Windows:

```python
# WSL:  neural.py  — contributes one fragment, serves it
src = cnv.neuron.source(sections=..., dt=0.025)
src.morphology(variable="v", name="morphology")
src.slider("stim", min=0, max=2, default=1.0)
cnv.serve("neural", transport=cnv.websocket(host="0.0.0.0", port=8765))

# Windows:  app.py  — orchestrates + renders
neural = cnv.remote("neural", transport=cnv.websocket("wsl.local", 8765))
cnv.layout(((neural.panel("morphology"),),))     # lay out the remote fragment locally
cnv.show()
```

**Symmetric case** — neural + physics co-simulation, frontend orchestrates ("remote
sources on both sides"):

```python
# WSL:  neural.py
cnv.serve("neural", transport=cnv.websocket(port=8765), peers=[cnv.remote("physics")])
# Windows:  physics.py
cnv.serve("physics", transport=cnv.websocket(port=8766), peers=[cnv.remote("neural")])
# Windows:  app.py  (orchestrator/frontend)
neural  = cnv.remote("neural",  transport=cnv.websocket("wsl.local", 8765))
physics = cnv.remote("physics", transport=cnv.websocket("localhost", 8766))
cnv.compose(neural, physics)
cnv.layout(((neural.panel("morphology"),), (physics.panel("body"),)))
cnv.show()
```

Each backend `serve`s one fragment and holds `remote` refs to its peers for direct
`RoutedMessage` traffic (co-sim ports); the frontend `show`s to own the composed
app. Neither backend owns the bus. No `ComposedBackend` anywhere — just fragments
integrated by the orchestrator.

## C3 — The layout crux: proxy handles vs. dynamic

The orchestrator's `cnv.layout(...)` must place a remote fragment's panels, but the
fragment is authored on the other side. Two options:

1. **Declared proxy handles (recommended).** `neural.panel("morphology")` is a local
   proxy laid out immediately; the real fragment must match that contract on connect
   (validated, clear error if not). Keeps "author the whole layout in one place."
2. **Dynamic post-connect.** Lay out local panels now; place remote fragments as
   they arrive over the wire via the runtime `PanelPatch` / `LayoutReplace` path.
   More flexible, but layout is no longer fully authorable up front.

Lean on (1); fall back to (2) only when a fragment's shape genuinely isn't known
until runtime. This is the same handle-placement model as the widget/control work
(Parts A/B) — a remote fragment contributes widgets and control panels the
orchestrator lays out by handle — just across a transport rather than in-process.

---

# Part D — The frontend as a swappable protocol

The inline layer must treat the frontend as an implementation detail. Today
`cnv.show()` *is* the VisPy frontend; the goal is for VisPy to be one conformant
implementation of a frontend **protocol** that anything else — a notebook host, a
Unity/C# client, a browser/WebGL renderer, a headless exporter — can reimplement.

## What already holds

- A frontend is already an actor peer: `FrontendBase(ActorBase)`. The bus routes
  every update to whichever actor is registered as `"frontend"`, so the frontend is
  already "any actor in that role."
- Two implementations already exist and are selected at runtime — the VisPy desktop
  window and the notebook host (which itself splits into `frontend` + `renderer` +
  `trace_renderer` role-actors). So "many frontends, one role" is proven, not
  hypothetical.
- `FrontendBase` is **empty on purpose.** There is no Python frontend *API* to
  implement. **The protocol is the message contract**, which is what lets a
  non-Python client implement the role without any CompNeuroVis Python at all.

## What the protocol actually is

A frontend is anything that, in the `"frontend"` routing role:

- **consumes** `AppSpecDeclared` (the app to render), `FieldReplace` / `FieldAppend`
  (data), `ValueChange` (control/state updates), `Status`, and later
  `PanelPatch` / `LayoutReplace`;
- **emits** `ValueChange` (control edits), `EntityClicked`, `KeyPressed`,
  `InvokeAction` — and, for a render-target actor, `RenderedFrame`.

That contract should be **stated** (a documented frontend-role protocol), not left
implicit in the routing tables and the VisPy source. Stating it is what turns
"reverse-engineer VisPy" into "implement the protocol."

## The gaps to close

1. **Open the selection.** `cnv.show(frontend=…)` with today's env auto-detection
   (notebook vs. desktop) as the *default*, and `frontend="vispy" | "notebook" |
   <FrontendProfile>` to choose or supply another. Frontends register like widgets
   (Part A) — a small frontend registry/profile — so a third-party frontend is a
   registration, not a fork of `show()`.
2. **Unbake VisPy from the run-spec builder.** `build_desktop_run_spec` hardcodes
   `VispyActorHost(VispyFrontendWindow, …)` as the frontend `host_source`. That
   becomes a parameter of the selected frontend profile, so the run-spec assembly is
   frontend-agnostic.

## Two swap paths (unifies with Part C)

- **In-process / Python frontend:** register a `FrontendBase` implementation; select
  it with `cnv.show(frontend=…)`. Same-process, no protocol serialization needed.
- **Remote / non-Python frontend:** the frontend is a peer that dials into the bus
  over a **network transport** and speaks the **serialized wire protocol** — it uses
  no CompNeuroVis Python. This is the `serve`/`remote` seam of Part C with the
  frontend as the remote actor, and it depends on the serializable protocol
  ([Design Directions §3](../design-directions.md)). So "swap the frontend" and
  "serialize the protocol" are two ends of the same requirement: a Python frontend
  swaps by class, a non-Python frontend swaps by wire.

Transport and frontend stay **independent axes** (as in the
[App Configuration Matrix](../app_configuration_matrix.md)): swapping VisPy→Unity is
orthogonal to swapping pipe→WebSocket; the matrix's remote rows are exactly the
cells where a frontend swap and a transport swap combine.

---

# Part E — Observability and configuration

Two cross-cutting cleanups that make the authored surface explicit and standard:
adopt conventional logging, and configure behavior through the API rather than
environment variables.

## E1 — Logging methodology

**Today:** there is no stdlib `logging` at all. Observability is a custom
`perf_log(component, event, **fields)` facility that writes structured JSONL, plus
stray `print()`s in hot paths (`"Meta file generated…"`, `"Morphology visual
generated…"`). There are no named loggers, no levels, and no way to turn on just one
subsystem.

**Direction — adopt standard library logging with hierarchical loggers ("log
groups").** Named loggers mirroring the architecture, so verbosity is scoped per
subsystem:

```
compneurovis
├── compneurovis.backend.neuron / .jaxley / .inline
├── compneurovis.frontend.vispy
├── compneurovis.transport / .bus
└── compneurovis.inline            # authoring
```

A user then does `logging.getLogger("compneurovis.transport").setLevel("DEBUG")` to
see only routing, etc. Conventions, following the norm for a library of this kind:

- **The library never configures handlers.** It attaches a `NullHandler` to
  `compneurovis` and emits records; the *application* owns handlers, levels, and
  formatting. No `basicConfig`, no writing to files or stderr by default.
- **Levels used normally:** `DEBUG` for per-frame/per-message detail, `INFO` for
  lifecycle (actor start/stop, app declared), `WARNING`/`ERROR` for real problems.
  The stray `print()`s become `logger.debug(...)`/`.info(...)` under the right
  namespace ([Design Directions §7](../design-directions.md)).
- **Contextual fields** (actor id, fragment id, frame) travel via `logging`'s
  `extra=` (or a structured-logging adapter), so per-actor/per-frame context is
  attachable without string-formatting it into the message.

**Perf telemetry stays a distinct channel.** The structured `perf_log` JSONL stream
is genuinely different from human logs — it's machine-analyzed timing data, not
messages — so it keeps its own opt-in channel rather than being forced through
`logging`. What changes is only how it's *enabled* (E2): via config, not env. Open
question: whether it becomes a `logging` handler emitting structured records, or
stays a separate sink; leaning separate, because its consumers (perf analysis
scripts) want a clean JSONL file, not interleaved log output.

## E2 — Configuration over environment variables

**Today** seven env vars drive behavior, in two groups:

| Env var | Drives |
|---|---|
| `CNV_NOTEBOOK_RENDER_PROCESS`, `CNV_NOTEBOOK_RFB`, `CNV_NOTEBOOK_BACKEND_PROCESS`, `CNV_NOTEBOOK_TRACE_DPI`, `CNV_NOTEBOOK_TRACE_QUALITY` | notebook rendering placement + quality |
| `COMPNV_PERF_LOG`, `COMPNV_PERF_STDERR` | perf telemetry enable/route |

Env vars are implicit, global, undiscoverable, don't compose, and — worst here —
drive **hidden branching** (the notebook render fork, flagged in
[Design Directions §7](../design-directions.md) and Part D). They should not be the
primary configuration mechanism.

**Direction — explicit config, passed at `show`/`serve`:**

- **Notebook rendering** (the 5 `CNV_NOTEBOOK_*` vars) becomes **frontend-profile
  configuration** — which is exactly the frontend selection of Part D. Render
  placement (in-kernel / RFB / render-process) and trace quality are fields of the
  chosen frontend profile, e.g. `cnv.show(frontend=cnv.notebook(render="process",
  trace_quality=…))`, not ambient env flags. This dissolves the notebook fork into a
  declared choice.
- **Perf telemetry** (the 2 `COMPNV_PERF_*` vars) already has an API path
  (`DiagnosticsSpec` → `configure_perf_logging`); make that the primary mechanism —
  `cnv.show(diagnostics=DiagnosticsSpec(...))` — and drop the env fallback (or demote
  it to a documented last-resort override, never the default path).
- **One place for config.** A small config object (extending `DiagnosticsSpec`, or a
  `RunConfig` carrying diagnostics + logging + frontend profile) passed to
  `show`/`serve`, so an app's runtime behavior is declared in one visible spot, the
  way its views and controls already are.

The test: reading an app's script should tell you how it will render and what it will
log, without also having to know which environment variables happen to be set.

---

# Part F — Testability: a headless drive API

**Problem.** There is no supported way to run an app for *N* ms without a frontend and
read the resulting state. Verifying the two ligand rewrites this session meant
hand-rolling the same harness three times: `runpy.run_path` the script with a mocked
`cnv.show`, then reach into internals — `src._make_backend()`,
`src._build_app_spec_for_backend(be)`, `be.initialize(app)`, and a `be.tick()` loop —
while reading model globals (`effector.effect`, `downstream.segment.v`) to confirm the
signal chain. The GUI cannot run in CI or in this environment, so **the golden /
characterization test strategy structurally depends on a headless driver existing**;
without one, these apps have no regression coverage at all.

**Proposal.** A first-class headless driver:

```python
run = cnv.drive(src, ms=125.0)        # tick the backend, no frontend, no event loop
run.field("Downstream HH voltage")     # emitted field history, for assertions
run.value("mod_gain")                  # latest control/state value
```

It composes the same app spec `show` does, drives `tick()` to a sim-time or
step budget, and captures emitted `FieldReplace`/`FieldAppend`/`ValueChange` into a
readable buffer — no private-attribute spelunking. This is **distinct from Part D's
"headless as a frontend"** open question: that one is a `FrontendBase` that consumes
updates and renders snapshots (pixels out); this is a *test driver* that ticks a
backend and inspects model/field state (values out, no rendering). It is the missing
tier-0 tool behind the harness strategy (golden fingerprints, characterization tests)
and the reason the ligand explorations can't currently be pinned against regression.

---

# Staged plan

1. **F — headless drive API.** `cnv.drive(src, ms=…)` returning readable
   field/value buffers. Independent, low-risk, and a prerequisite for regression-
   testing everything that follows — so it ships first, turning "verify against
   golden behavior" from aspiration into something runnable in CI.
2. **B1 + B4 + `bind` — control ergonomics.** Per-type control calls, the `bind`
   attribute helper, and defaults-authoritative. All pure additive sugar over
   `control(...)`; no core changes, reversible, immediately improves every inline
   file. Lands with Part F coverage.
3. **A — widget registry + generic dispatcher.** Introduce `WidgetKind` /
   `register_widget`, the generic `WidgetRuntime` in the frontend, registry-based
   validation and routing. Migrate the five existing widgets (now uniform
   `PanelHandle` subclasses); keep the morphology escape hatch. Verify against golden
   behavior.
4. **B2 — control panels.** Land `control_panel(...)` as a `controls` widget
   instance on top of A, with panel-scoped control authoring and the default-panel
   back-compat path.
5. **B3 — dependent / dynamic controls.** The first handle-mutation surface:
   `handle.reconfigure(...)` / `depends_on=` lowering to the existing wired
   `ControlPatch` (+ `ValueChange`) — a peer of `ViewPatch`, no new message. This
   exposes what the core already models and is the beachhead for the wider "settable
   whenever" model ([through-line](../design-directions.md)). Settle the value/spec
   boundary (bindable props vs `ControlPatch`) first.
6. **First new widget via the public path** — a `graph`/connectivity widget
   (the [network-plotting backlog item](../backlog.md)) authored entirely through
   the registry, as the proof that the layer works from outside core.
7. **C — wire composition to `build_integrated_app_spec`.** Make `cnv.compose(...)`
   and multiple local sources lower through the already-built fragment integrator
   (removing the `ComposedSource` stub), and settle `CompositeBackendActor` as a
   pure co-location host (or replace it with per-fragment channels). Local
   composition first, no transport changes.
8. **C — `serve` / `remote` + proxy handles across a seam.** Depends on the network
   transport ([Design Directions §3](../design-directions.md)). Lands the
   distributed authoring surface: `cnv.serve(...)`, `cnv.remote(id, transport=)`
   returning proxy handles, and cross-seam layout via option C3(1).
9. **D — state the frontend protocol.** Document the frontend-role message contract
   (consumes/emits) so it is implementable without reading VisPy. No code change;
   unblocks any non-Python frontend author. Can ship early, independent of the rest.
10. **D — open the frontend selection.** `cnv.show(frontend=…)` + a frontend
    registry/profile; unbake VisPy from `build_desktop_run_spec`. Then a second
    Python frontend (or a headless exporter) proves the seam in-process before a
    remote non-Python frontend exercises it over the wire.
11. **E1 — adopt stdlib logging.** Hierarchical `compneurovis.*` loggers + a
    `NullHandler`; convert the stray `print()`s to `logger` calls. Low-risk,
    independent, ships anytime.
12. **E2 — config over env.** Route perf telemetry through `DiagnosticsSpec` and
    drop the env fallback; fold the five `CNV_NOTEBOOK_*` flags into the frontend
    profile (rides on D). Delete the env-var reads once each has an explicit home.

# Open questions

- **Registration location.** Do third-party widgets register at import time
  (module side effect) or through an explicit app-level registry passed to
  `cnv.show(...)`? The latter is more testable and avoids global state.
- **Renderer contract width.** Is `refresh(view, fields, values)` enough for most
  kinds, with an opt-in richer host contract (selection/camera) for
  morphology-class widgets — or do we need two tiers of widget from the start?
- **Backend-side data.** A widget's data field still comes from a backend/source
  (`record_refs`, `derive`, an `ArrayFieldBinding`). Does the widget registration
  say anything about data production, or does it stay purely a view/panel/refresh
  contract with data left to the existing field-source vocabulary? (Leaning: keep
  them orthogonal — widgets render fields; sources produce fields.)
- **The origin-agnostic sampleable.** The [through-line](../design-directions.md)
  wants `record_refs` / `line(read=)` / `line(source=)` unified behind one `sample()`
  concept so panels don't branch on data origin. Is that one `Sampleable` protocol
  with adapters (NEURON ref, callable, existing field, remote field), and does its
  *cadence* (`record_refs` samples per solver step; `read=` per emit batch) become an
  explicit property of the sampleable rather than an accident of which call you made?
  Mixing the two in one figure today gives different temporal resolution with no
  signal to the author.
- **Dependent-control re-spec scope (B3).** How much of a control's spec is mutable at
  runtime — value and default only, or the full `options` / `min` / `max` / `label`?
  And is the dependency declared statically (`depends_on=`, so the graph is
  inspectable/serializable) or driven imperatively from a `set` callback (simpler, but
  opaque to a remote frontend that must render the re-spec)?
- **Defaults-authoritative default (B4).** Is applying a declared `default=` to the
  model always-on, or opt-in? Always-on is the least-surprising for the slider→model
  contract, but it clobbers a model deliberately constructed to differ from its UI
  default; opt-in keeps that escape hatch at the cost of the footgun returning.
- **Headless drive vs `show` composition (F).** `cnv.drive` must build the *same* app
  spec `show` does, or the thing tested diverges from the thing shipped. Does `drive`
  share `show`'s composition path exactly (only swapping the frontend for a capture
  sink), and does it expose raw emitted messages, resolved field arrays, or both?
- **Per-type control coverage.** Six typed calls cover the current value specs.
  Do we also want composite helpers (e.g. a labeled slider group) as sugar, or
  keep those in user code?
- **`CompositeBackendActor`'s fate.** Keep it as a pure co-location host (N
  in-process fragments, one channel) for the script-rerun path, or give every
  fragment its own channel and delete it? The former is a harmless optimization;
  the latter is conceptually cleaner (every fragment is a plain peer everywhere).
- **`show` vs `serve` for a lone backend.** A headless backend with no frontend
  (batch/export) — is that `serve` with no orchestrator, or `show` on the backend
  itself? Clarify which verb owns the bus when there is no frontend.
- **Proxy-handle contract.** What does `neural.panel("morphology")` guarantee at
  authoring time, and how loud is the mismatch when the connected fragment doesn't
  provide it — hard error, or best-effort placement?
- **Frontend protocol versioning.** Once the frontend-role message contract is
  stated and a non-Python client implements it, the message set becomes a public
  contract. How is it versioned so a Unity/browser client and the Python backend can
  evolve without lockstep releases?
- **Headless as a frontend.** Is a headless exporter (render snapshots / write
  files, no event loop) just a `FrontendBase` that consumes the same updates and
  emits nothing — confirming the protocol covers the no-interaction degenerate case?
- **Perf telemetry channel.** Does `perf_log` become a structured `logging` handler,
  or stay a separate JSONL sink? (Leaning separate — perf-analysis consumers want a
  clean file, not interleaved log output.)
- **Config object scope.** Is there one `RunConfig` (diagnostics + logging + frontend
  profile) passed to `show`/`serve`, or do these stay as separate keyword arguments?
- **Env-var override policy.** Are env vars removed entirely, or kept as a documented
  last-resort override (e.g. for CI) that never shadows an explicit config value?

# Cross-links

- [Design Directions §1](../design-directions.md) — the open panel/view registry
  (this proposal is its concrete authoring form).
- [Design Directions §6](../design-directions.md) — the authoring-tier thesis
  (`Feature` bundles are the next layer above this).
- [Backlog](../backlog.md) — network/`GraphGeometry` plotting (the first new
  widget) and controls-density policy (resolved by B2).
