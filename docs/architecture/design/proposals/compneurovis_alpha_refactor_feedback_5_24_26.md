# CompNeuroVis Alpha Refactor Feedback

## Overall assessment

The refactor is directionally strong. The current architecture is moving toward a cleaner separation between declarative app structure, live runtime projection, actor topology, routing, and inline authoring. The strongest pieces are the `FieldSpec` vs. `Field` split, `AppSpec` as a catalog-structured declaration, `AppProjection` as actor-local live state, `RunSpec` as runtime topology, and inline authoring through source objects rather than root-level global `trace/control/action` functions.

The main risks are not that the architecture is wrong. The main risks are that a few implementation shortcuts could harden into public semantics: porous immutability, ambiguous declaration vs. projection boundaries, unsafe default routing in multi-actor setups, Python-object-specific message payloads, and incomplete inline action semantics.

## Highest-priority issues

### 1. Make declarative specs genuinely immutable

`FieldSpec` and related specs are frozen dataclasses, but they contain mutable NumPy arrays and dictionaries. Freezing the dataclass prevents rebinding attributes, but it does not prevent mutation of array contents or nested dictionaries. This weakens the declaration/runtime split.

Recommended direction:

- Treat specs as immutable snapshots.
- Defensively copy arrays and coordinate dictionaries during construction.
- Consider setting arrays to read-only with `setflags(write=False)`.
- Keep runtime mutation confined to `Field`, `AppProjection`, and update handling.

This matters because `FieldSpec` should be a stable startup declaration, while `Field` should represent live actor-local data.

### 2. Clarify whether `AppSpec` is raw declaration or normalized declaration

`AppSpec` currently normalizes layout during construction. This is practical, but it means `AppSpec` is not simply preserving the user-declared structure. It becomes partly resolved/normalized during initialization.

Recommended direction:

- Either move layout normalization into `AppProjection` or a `ResolvedAppSpec` layer.
- Or explicitly define `AppSpec` as a normalized declaration, not a raw declaration.

The cleaner long-term model is probably:

```text
AppSpec: user-declared structure
AppProjection: resolved, normalized, mutable actor-local view
```

This would preserve the conceptual boundary between declaration and runtime state.

### 3. Make bus fallback routing stricter for multi-actor runs

The `Bus` routing priority is conceptually good: explicit routed message, then routing rules, then default command/update targets, then fallback broadcast. The risky part is fallback broadcast. In a two-actor setup it is convenient. In a multi-actor topology it becomes a footgun.

Recommended direction:

- Allow fallback broadcast for simple two-actor runs.
- Warn or raise when there are more than two actors and no explicit route/default target exists.
- Require explicit routing when multiple backend-like or source-like actors are present.

This is important because the refactor is explicitly moving toward composed sources, remote actors, and multi-actor runtime graphs. Silent broadcast should not become the default behavior for underspecified topologies.

### 4. Decide how transport-serializable the protocol is meant to be

The message layer currently carries concrete Python dataclass objects such as `AppSpec`, `PanelSpec`, and other in-memory constructs. This is fine for local Python alpha workflows, but it couples the protocol to Python object graphs.

Recommended direction:

- For now, this can remain a local Python protocol.
- But mark the future boundary clearly: transport-level messages may need a serializable representation.
- Consider separating protocol envelopes from app-specific payload classes.
- Avoid allowing arbitrary Python objects into fields that may eventually cross a process or remote boundary.

The main question to answer explicitly is: is the protocol currently a local in-memory Python protocol, or is it intended to become a stable cross-process/cross-language transport schema?

### 5. Fix inline action payload semantics early

`ActionSpec` includes concepts like payload, shortcut, selection mode, and selection payload key. But inline action functions currently appear to be called as plain zero-argument functions. That risks a mismatch between the declarative action model and runtime inline behavior.

Recommended direction:

- Decide on an action function signature before many examples accumulate.
- Consider passing payload and/or context to action functions.

Possible shapes:

```python
def action_fn(payload): ...
```

or:

```python
def action_fn(ctx, payload): ...
```

Selection-driven actions especially need a way to receive frontend-generated payloads.

## Medium-priority architectural concerns

### 6. Keep the catalog-based `AppSpec` as the canonical model

`AppSpec` currently supports both the new catalog-structured form and older flat constructor forms. That is useful during refactor, but both forms should not remain equally canonical indefinitely.

Recommended direction:

- Make catalog-based construction the internal/core canonical model.
- Keep flat forms as temporary migration shims or builder-level conveniences.
- Avoid writing new examples that imply the flat constructor is the conceptual core.

The catalog split is stronger:

```text
DataCatalog: fields and geometries
ViewCatalog: views and operators
InteractionCatalog: controls and actions
LayoutCatalog: layouts and panels
```

### 7. Add validation for routing rules

`MessageMatch.attrs` is flexible, but it is weakly typed. A typo in an attribute name, a payload field rename, or a wrong value type can silently break routing.

Recommended direction:

- Add validation for `RoutingSpec` against registered message payload types.
- Check that message type names exist.
- Check that matched payload attributes exist on the corresponding payload dataclass.

This preserves flexible routing while catching avoidable bugs.

### 8. Treat global `cnv.show()` as inline-session sugar, not a core primitive

The current inline API is much better than the earlier global `cnv.trace/control/action` or `cnv.monitor` approach. Source objects own `trace`, `control`, and `action`, while `cnv.show()` is a convenience.

The remaining risk is that `cnv.show()` relies on module-level singleton state. This is ergonomic for scripts and notebooks, but it has predictable edge cases:

- Rerunning notebook cells.
- Multiple independent demos in one process.
- Test leakage.
- Conditional source creation.
- Source objects surviving after inline session reset.

Recommended direction:

- Keep `cnv.source(...); cnv.show()` as ergonomic sugar.
- Consider a more explicit session/app object as an escape hatch later:

```python
app = cnv.inline.App()
src = app.source(...)
app.show()
```

### 9. Avoid making composition look stable before lowering semantics exist

`ComposedSource` and remote source concepts are good architectural scaffolding, but composition currently does not lower to a real multi-actor runtime. The code correctly avoids hiding composition inside a single backend wrapper, but the public API could still imply that composition is supported.

Recommended direction:

- Keep composition/remote APIs clearly experimental until lowering is implemented.
- Or implement a limited explicit lowering into `RunSpec` soon.

The correct long-term model is that composed sources compile into explicit actor topology, not one opaque backend actor.

### 10. Separate simulation step rate, sample rate, message flush rate, and render/update rate

The inline backend currently has a fixed 60 Hz-ish loop. That is acceptable for demos, but it conflates several different clocks:

```text
simulation integration timestep
sampling timestep
frontend update rate
message flush rate
render cadence
```

Recommended direction:

- Keep the current loop for now if it is practical.
- Do not bake it into public semantics.
- Eventually expose clock/update policy on sources or run specs.

Possible future API ideas:

```python
src = cnv.source(model, update_hz=60)
```

or:

```python
src.clock(update_hz=60, sample_policy="manual")
```

## Lower-priority design smells to monitor

### 11. `ValueOrBinding = Any` weakens the declarative type system

Many view/control fields can accept either literal values or bindings. Using `Any` is pragmatic, but it makes it easy to accidentally put non-serializable or unintended Python objects into core specs.

Recommended direction:

- Eventually replace `Any` with a narrower union or validation layer.
- At minimum, validate values before crossing process/transport boundaries.

### 12. `RenderedFrame` may belong to a separate output stream

`RenderedFrame` is conceptually different from field/view/control/layout updates. It represents a rendered artifact, not an app-model update.

Recommended direction:

- Keep it if needed for remote/headless rendering.
- But monitor whether rendered artifacts should become a separate message stream or actor output type.

## What not to overcorrect

Do not revert the main direction of the refactor. The branch is stronger because it now separates:

```text
FieldSpec vs Field
AppSpec vs AppProjection
App declaration vs runtime topology
Actor peers vs bus infrastructure
Inline authoring vs core model
Source composition concept vs actual runtime lowering
```

The goal should be to preserve those separations while tightening the places where the boundaries are currently porous.

## Suggested immediate action list

1. Make `FieldSpec` and other spec arrays/dicts defensively immutable.
2. Decide whether layout normalization belongs in `AppSpec`, `AppProjection`, or a resolved-spec layer.
3. Restrict or warn on fallback broadcast routing in multi-actor topologies.
4. Decide whether the message protocol is local-Python-only for now or should begin moving toward serializable payloads.
5. Update inline action function semantics to receive payload/context before examples depend on zero-argument actions.
6. Mark composition/remote source APIs as experimental unless real lowering is implemented soon.

## Bottom line

The refactor is structurally promising. The major abstractions are pointed in the right direction. The main work now is to prevent alpha conveniences from becoming implicit platform contracts. The issues to address are mostly boundary-hardening problems: immutability, declaration vs. projection, routing specificity, transport serialization, and action payload semantics.

