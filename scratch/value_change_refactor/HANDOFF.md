# Handoff — control→value ("ValueChange") refactor — Superseded

This completed refactor record targets removed APIs and is retained only as
throwaway scratch history. Do not use its TODO table or golden artifacts as current
work. Current protocol authority is `src/compneurovis/core/messages.py`; current
architecture is documented under `architecture/design/`.

Reframe the interaction layer around a symmetric actor model. Phases A–C are
**done and verified**; D–E remain. Everything here is validated by golden
harnesses in this folder.

---

## 1. The goal / design

**The backend must not model "controls."** A control is a UI affordance (slider,
dropdown, label, presentation) *bound to a value*. All of that is authoring +
rendering vocabulary. From any actor's perspective, the only thing that happens
is **a keyed value changed.**

Grounded in the code: `MessageType.allowed_intents` is a tuple (one type can be
both `command` and `update`); `ActorBase` emits/handles symmetrically; the Bus
routes purely by `RoutingSpec` (config), not by role; `RoutedMessage` lets any
actor address any peer. **Nothing is privileged or directional.** A backend is
just the actor that happens to own model-parameter keys; a frontend owns
layout/display keys.

**Target model:**
- One symmetric message `ValueChange(updates: {key: value})`, `allowed_intents =
  (command, update)` — subsumes `SetControl` (command) and `BindingValuePatch`
  (update). command flavor = "please set"; update flavor = "now set".
- Every actor holds a `ValueBindings` registry: `{ key: handler(actor, value) }`.
  `handle(ValueChange)` applies keyed changes to whatever it bound.
- A control **compiles to three role-neutral outputs**: a render spec (into the
  app-spec, for whatever actor draws UI), a `key→handler` registration (on the
  source's actor), and a route (by fragment tag).
- **No 1:1 assumption.** N backends, M frontends, remote actors. Placement is
  inferred from *fragment membership* (which source a control was declared on →
  which actor), never authored — inline authors know nothing about actors/roles.

**Flexibility check (already confirmed):** a handler is arbitrary and can emit
any update — `FieldReplace` (sim), `LayoutReplace`/`PanelPatch` (layout/controls),
`AppSpecDeclared` (nuclear). So "a dropdown/button that changes the sim, the
layout, or the control set" all work; the reframe changes the *trigger* (keyed
value / event), not what a handler may *do*.

---

## 2. Phases

| Phase | What | Status |
|---|---|---|
| **Step 0** | Strengthen the runtime golden to exercise the control→effect path (apply first control, capture effect). Re-baseline. | ✅ |
| **A** | Add `ValueChange` payload + `VALUE_CHANGE` type (both intents); add `ValueBindings` to `core/actor.py`. Additive, nothing wired. | ✅ |
| **B** | All three backends `handle(ValueChange)` → delegate to existing `apply_control` per key. `SetControl` still primary. Dual-path. | ✅ (proven byte-identical to SetControl) |
| **C** | `frontend.py::_on_control_changed` + `notebook_host.py` emit `ValueChange({key: value})` (fragment-tagged) instead of `SetControl`. Routing needs **no change** (generic/fragment command routes already catch it). | ✅ (compile + routing-resolution verified) |
| **D** | Remove `SetControl`. Collapse `apply_control`/`control_specs`/`control_values`/`_apply_backend_control` (+ mixin control methods) into `ValueBindings`. Fold `BindingValuePatch` into `ValueChange` (update intent). Remove dead per-control `set_control` routes. | ⏳ TODO |
| **E** | Reframe the frontend refresh-planner as `ValueBindings` on the frontend actor (frontend as a value peer that handles `ValueChange` updates for keys its panels subscribe to via `StateBindingSpec`). | ⏳ TODO, separable |

---

## 3. Exactly what's been changed (files)

- `core/messages.py` — `ValueChange(updates)` payload; `VALUE_CHANGE =
  _message_type("value_change", ValueChange, ("command","update"))`; added to
  `MESSAGE_TYPES`.
- `core/actor.py` — new `ValueBindings` class (`bind`/`handles`/`get`/`snapshot`/
  `apply`). Not yet wired into `ActorBase.__init__` (backends will compose it in D).
- `backends/neuron/backend.py`, `backends/jaxley/backend.py`,
  `inline/backend.py` — `handle(ValueChange)` → `apply_control(key, value)` per
  key (dual-path alongside `SetControl`). Imports of `ValueChange` added.
- `frontends/vispy/frontend.py` — `_on_control_changed` emits
  `ValueChange({local_control_id: value})` (was `SetControl`). Import added.
- `frontends/vispy/notebook_host.py` — `_on_change` emits `ValueChange`. Import added.
- Routing (`_source_runtime.py`) — **unchanged**; already routes `value_change`
  commands (generic + fragment-tagged). Dead per-control `set_control` routes
  remain (remove in D).

> Also in this session (background context, already landed + golden-verified):
> the backend `tick` was **de-forked** (base owns one seamed loop with
> `_advance`/`_on_step`/`_sample_step` + `_flush_dt`; `_SourceBackend` extends via
> those seams, no fork), `initialize(AppSpec | None)` replaced a `getattr` smell,
> and standalone backend **independence** was proven. The value-change work sits
> on top of that.

---

## 4. Golden validation (in this folder)

All harnesses here. **Behavior has stayed identical through Phase C, so the
current state == original behavior** — the baselines are valid references for D/E.

- **`runtime_golden.py`** — per-tick emission fingerprint of a *source backend*,
  driven `init → 15 ticks → apply first control → 10 ticks → reset → 5 ticks`,
  recording every emitted message (type, field_id, shape, value checksum).
  - `python runtime_golden.py capture <example.py> <baseline.json>`
  - `python runtime_golden.py compare <example.py> <baseline.json>`
  - Env `USE_VALUE_CHANGE=1` makes the control step emit `ValueChange` instead of
    `SetControl` — used to prove the two paths are byte-identical.
  - Baselines here: `rt_neuron_point.json`, `rt_neuron_multi.json`,
    `rt_jaxley_multi.json`.
  - Examples: `neuron/hh_point_model_controls.py` (has controls — guards control
    path), `neuron/multicell_example.py` (no controls), `jaxley/multicell_example.py`
    (has controls). Run **one example per process** (NEURON/jax global sim state).
- **`golden.py`** — structural app-spec fingerprint (fields/views/geoms/panels/
  grid/controls) for 13 examples. `python golden.py capture|compare`. Baseline
  `golden.json`. NOTE: this baseline predates a parallel widget refactor by
  another agent, so some entries currently DIFF for unrelated reasons —
  **re-capture before trusting it.**
- **`standalone_neuron.py` / `standalone_jaxley.py`** — prove each backend runs
  with **no source layer** (subclass the base backend, `build_startup_data()`,
  `initialize(None)`, click, tick → emits display+history). Run directly.

**How to validate D/E:** re-`capture` the three `rt_*` baselines at the current
(green) state, do the phase, then `compare` — must be identical. Run the standalone
smokes too (independence must survive).

**Coverage caveat:** the runtime golden drives the **backend directly** (bypasses
frontend + bus). So it validates backend behavior and the control→effect, **not**
the frontend emit or bus routing. Those were verified separately: routing
resolution was unit-checked (a `value_change` command matches the generic
`command→backend` route); the frontend/notebook swaps were compile-checked + code
reviewed. **Actually moving a slider in the GUI is a human check** (can't drive Qt
headless here).

---

## 5. Gotchas for Phase D/E

- **Routing is by fragment TAG, not by key.** `Bus._matches` compares scalar
  attrs; a `ValueChange.updates` dict can't be attr-matched by key. The frontend
  already tags control changes with `fragment_id` (`_command_ref`), and
  `build_multi_source_routing` routes commands by that tag. Keep it that way.
- **`resolved_state_key == control_id` in practice** (inline controls never set a
  custom `state_key`). So today the wire key == `control_id`, and `handle(
  ValueChange)`→`apply_control(key)` works because `apply_control` matches
  `control_id`. In D, make the key explicitly `resolved_state_key` and have
  `ValueBindings` key on the same.
- **Preserve everything `apply_control` does** when collapsing into `ValueBindings`:
  source-control setters (via `control.apply(backend, value)` — builds ctx, runs
  setter), neuron's **segment-variable dropdown** branch (a special `apply_control`
  case → must become a bound handler), `control_hooks`
  (`_notify_source_control_changed`), and `_ui_state[key] = value`. The natural
  handler is `control.apply`; the segment-var dropdown needs its own bound handler.
- **`send_to_backend` gating currently lives in the frontend** (it only emits for
  `send_to_backend` controls). Preserve, or generalize to "route to whichever
  actors bound the key."
- **`_apply_backend_control` (neuron)** is dead in source mode (unmatched ids only)
  and a latent footgun (`setattr` junk) — it dissolves in D. Base
  `NeuronBackend.apply_control` (`setattr`) stays as the *standalone* control path.
- **`control_values()`** consumers (`ctx.controls()` in `backends/interaction.py`)
  → `ValueBindings.snapshot()`/`get`.
- **Deferred / not in scope:** UI-local handler placement to avoid a
  frontend→backend→frontend round-trip for pure-layout controls (correct as-is,
  just not optimal — needs a role-neutral "this effect is UI-local" signal).
  Actions/clicks/keys stay as events (`InvokeAction`/`EntityClicked`/`KeyPressed`);
  they could fold into the same topic→handler model later but are out of scope.
