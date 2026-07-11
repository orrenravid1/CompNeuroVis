# Alpha Release Cleanup Review

**Date:** 2026-07-11
**Branch:** `user/orren/alpha-release`
**Purpose:** Inventory the skills, docs, tests, scratch, examples, and overall repo
state ahead of an alpha release. This is a *pre–burn-down* survey: structure and
purpose of each area, plus how far each has drifted from the current codebase.
No files were changed to produce it.

**Method:** collection/import checks, `py_compile`, terminology greps against the
current vs. removed API, running the doc/index generators, and `git ls-files` /
`git log` to separate tracked assets from local cruft.

---

## TL;DR

All three review targets (tests, docs, skills) are pinned to the **pre-refactor
architecture** — the `Session`/`builders`/`SetControl`/`attach` world — and the
tooling meant to keep them honest is itself broken against the current tree. The
current inline authoring API (`cnv.neuron.source`, `cnv.layout`, `src.morphology`)
and the actor/`ValueChange` runtime appear in **zero** docs.

The good news: the **examples are current and healthy** (21/21 on the live API,
all compile) and the working tree is committed and clean. The cleanup is
concentrated, not sprawling.

| Area | Health | One-line verdict |
|---|---|---|
| Examples | 🟢 good | On current API, all compile; only a BOM-encoding wart |
| Repo state | 🟡 mixed | Clean git, but empty dead dirs + a 272M stray log + stale AGENTS.md |
| Skills | 🟡 stale | Structurally intact, but 14/24 reference the old architecture |
| Docs | 🔴 stale | Describes a superseded architecture; generators crash |
| Tests | 🔴 broken | 10/19 files don't import; of the rest, 14 tests fail |
| Scratch | 🔴 junk | 275M, mostly one stray log; mix of live + dead-API spikes |

---

## 1. Repo state

- **Git:** clean working tree (0 uncommitted), on `user/orren/alpha-release`.
  Recent history is coherent (`Saving CNS poster`, `Added various widget examples`,
  `Fixed…bus routing order`).
- **Empty leftover packages:** `src/compneurovis/{session,builders,relays}/` exist
  on disk as **empty dirs** (0 `.py`, 0 tracked, not gitignored) — residue of a
  `git rm` that left the directories behind. Harmless but confusing.
- **Tracked dead code:** `src/compneurovis/deprecated/` — 6 files, ~416 LOC,
  tracked, imported by nothing. The only real dead code (the empty dirs above are
  just noise).
- **`AGENTS.md` is stale (last touched 2026-05-06).** Its "Stable Package Map"
  still lists `session` and `builders` as canonical packages and its Public API
  Map predates the inline API. `README.md` (2026-04-23) likely similar. For
  contrast, `src/compneurovis/__init__.py` was current as of 2026-07-08.
- **UTF-8 BOM problem:** 15 of 21 example `.py` files (and 1 `src` file) start with
  a `﻿` BOM. `py_compile` tolerates it, but any tool that reads the file as
  plain UTF-8 and `ast.parse`s it breaks — which is exactly why the index
  generator crashes (see §4). The 6 BOM-free examples are the widget examples
  written most recently.
- **Stray top-level dirs:** `0/` (empty, untracked), `site/` (built mkdocs output,
  gitignored), `.compneurovis/` (56M perf logs), `CNS2026/` (2.1M, 3 files tracked —
  poster materials).

---

## 2. Tests — `tests/` (19 files, 208 tests)

**10 of 19 files fail to import** because they reference symbols/modules the
refactor removed:

| Broken import | File |
|---|---|
| `ActorRole` | test_pipe_transport |
| `AttributeRef` | test_core_bindings |
| `GridGeometry` | test_geometry |
| `MorphologyGeometry` | test_frontend_bindings ⚠️ |
| `build_replay_app` | test_replay_builder |
| `JaxleyAppSpecBuilder` | test_jaxley_scene |
| module `core.app` | test_layout_updates |
| module `compneurovis.messages` | test_messages |
| module `backends.neuron.app_spec` | test_neuron_backend |
| module `compneurovis._perf` | test_perf_logging |

Of the **9 files that do import: 33 pass, 14 fail, 7 skip** (jaxley not installed).
The failures are stale assertions about app-spec structure, doc/index sync,
vocabulary rules, and packaging metadata.

**Purpose split:**
- **Functional/unit** — field, app_spec, messages, core_bindings, geometry,
  frontend_bindings, neuron/jaxley backends, jaxley_scene, layout_updates,
  pipe_transport, perf_logging, replay_builder.
- **Meta-tests** validating the docs/skills/tooling themselves — docs_and_indexes
  (17 tests), docs_vocabulary, pr_readiness, packaging_metadata,
  generate_mcp_configs. These are why "stale docs" surfaces as red test output.

**Biggest single asset at risk:** `test_frontend_bindings.py` — 3115 lines,
**85 tests**, the real functional coverage of the frontend — is in the broken set
(`MorphologyGeometry`). Salvageability of these 85 tests is the main open question
for the tests burn-down and is worth a dedicated read.

---

## 3. Docs — `docs/` (52 files, 49 markdown)

**Describes a superseded architecture.** Terminology census:

| Term | Files | Status |
|---|---|---|
| `session` | 34 | old runtime vocabulary |
| `SetControl` | 11 | removed message type |
| `attach` | 6 | removed API |
| `ValueChange` | **0** | current message type |
| `cnv.neuron.source` / `cnv.layout` / `src.morphology` | **0** | current API |

`api/public-api.md` documents `Session`, `build_surface_app`, `build_replay_app`,
`build_neuron_app`, `build_jaxley_app` — all part of dead/removed code.

**Structure and purpose:**
- **Authored user docs** — `getting-started.md`; `concepts/` (6: field-model,
  controls-actions-state, session-update-model, view-layout-model, geometry-types,
  index); `tutorials/` (5: neuron / jaxley / replay / surface + index); `api/` (4).
- **Architecture** — `core-model`, `session-protocol`, `runtime-architecture-map`,
  `vispy-frontend`, plus machine-readable `invariants.json` and
  `docs-vocabulary.json` that scripts enforce.
- **Design** — `design/proposals/` (14): a mix of **dated historical snapshots**
  (refactor logs, state-of-repo audits, May–June) that are defensible to keep as
  history, and **undated living proposals** (websocket-transport, layout-workbench,
  poster-submission, composable-authoring-proof, panel-layout-updates) that read as
  forward guidance and need a keep/kill decision.
- **Generated reference** — `reference/` (api-index, example-index, skill-index,
  repo-map), produced by `scripts/generate_indexes.py`.

**The generators are broken.** `scripts/generate_indexes.py` crashes on the BOM in
`examples/custom/fitzhugh_nagumo_backend.py`, so the reference indexes cannot
regenerate. `example-index.md` lists 17 of the 21 examples on disk.

**Supporting tooling** (`scripts/`): `generate_indexes`, `check_docs_vocabulary`,
`check_packaging_metadata`, `check_architecture_invariants`, `generate_mcp_configs`,
`mkdocs_hooks`, `pr_readiness` — these back the meta-tests in §2.

*Not cleanly verified:* mkdocs `nav` ↔ disk sync (first check was buggy); whether
every "session" mention is the dead class vs. the generic notion of a running app.

---

## 4. Skills — `skills/` (24 skills)

**Least broken, but built for the old layout.** Each skill is one `SKILL.md`;
4 carry support files (`agents/openai.yaml` cross-tool shims; one helper script
under `audit-source-organization/scripts/`). Drift: **14/24 mention "session"**,
2 reference dead `builders`, and `audit-code-smells` / `audit-layer-boundaries`
hardcode `compneurovis/session` and `compneurovis/builders` src paths.

They are a **meta-tooling layer**, not user-facing — three families:
- **Authoring workflows** — add-control, add-example, add-field-visualization,
  add-simulator-backend, add-view-panel.
- **Audits / checks** — audit-* (architecture-doc-consistency, code-smells,
  layer-boundaries, skill-coverage, skill-freshness, source-organization) and
  check-* (change-impact, concept-coverage, docs-coverage, test-coverage-drift,
  tutorial-coverage).
- **Process** — plan-refactor, pr-readiness, register-skill, update-docs-and-indexes,
  breaking-rename-sweep, debug-rendering, debug-protocol-dataflow, scratch-exploration.

Several skills describe workflows that only make sense against the meta-tests and
generators that are currently broken (§2, §3), so they can't be exercised end-to-end
until those are fixed.

---

## 5. Examples — `examples/` (21 `.py`, 2 notebooks) — the healthy one

- **All 21 use the current inline API** (`cnv.source` / `cnv.neuron.source` /
  `cnv.layout`); **0 use the removed `.attach` API.**
- **All 21 compile** (`py_compile`).
- **Only wart:** 15/21 carry a UTF-8 BOM (§1), which breaks `ast.parse`-based
  tooling and is the root cause of the index generator crash. Stripping the BOMs
  is a one-line fix that also unblocks doc regeneration.

**Layout:** `custom/` (2), `debug/` (4), `jaxley/` (1), `neuron/` (6),
`surface_plot/` (4), `widgets/` (4: bar_plot, controls, state_graph, surface).
The `widgets/` group is new this session and is the cleanest reference set.

Note: `examples/debug/session_error_after_open.py` still carries the old "session"
name in its filename.

---

## 6. Scratch — `scratch/` (72 files, 275M)

- **275M is almost entirely one stray file:** a nested
  `scratch/scratch/.compneurovis/notebook-logs/…mainprocess…jsonl` at **272M**,
  from an accidental `scratch/scratch/` created by a notebook run. **Untracked** —
  not in git — so it's local-disk-only, but it should be deleted and the nested
  path guarded against.
- **Tracked content:** 43 files, including 3 junk artifacts (`.png` / `.log` /
  `.txt`, e.g. `perf_stats.txt`, `notebook_debug.log`, `sweep.png`) that shouldn't
  be committed. `__pycache__` is not tracked (good).
- **Spikes:** 27 `.py`. Split ~evenly between the **removed `.attach` API** (3
  files, e.g. `hh_neuron_attach.py`, `hh_jaxley_attach.py`) and the **current
  inline API** (3), plus sweep/validation scripts and Ctrl-C repro tests.
- **`value_change_refactor/`** — a self-contained harness (HANDOFF.md, golden.py,
  runtime_golden.py, standalone_*.py, JSON baselines) from the ValueChange refactor.
  `runtime_golden.py` itself no longer imports (references removed `SetControl`).
- **`source_organization_review.md` / `backend_layer_inventory.md`** — prior review
  notes worth reading before the src cleanup.

Scratch is by definition disposable, but it currently mixes throwaway logs, a
huge stray file, and a few genuinely useful harnesses/notes.

---

## 7. Cross-cutting root causes

1. **One refactor, three unmigrated trees.** The Session→actor / SetControl→ValueChange /
   attach→source refactor updated `src/` and `examples/` but not tests, docs, skills,
   or AGENTS.md. Every red result traces back to that.
2. **The self-check tooling is down.** Index generation, docs-vocabulary, packaging,
   and app-spec assertions all fail — so the mechanisms that would normally *flag*
   drift are themselves casualties of it, and can't be trusted as a burn-down signal
   until repaired.
3. **A BOM-encoding wart** is quietly load-bearing: it blocks index regeneration and
   any `ast.parse`-based check across 15 example files.

---

## 8. Suggested burn-down scope (for discussion, not yet acted on)

Ordered by leverage:

1. **Strip UTF-8 BOMs** from the 15 examples + 1 src file. Unblocks the index
   generator and `ast.parse` tooling in one shot.
2. **Delete dead source** — empty `session/`/`builders/`/`relays/` dirs and the
   tracked `deprecated/` package — then rewrite `AGENTS.md`'s package + API maps to
   the real layout. This is the anchor the docs/skills/tests all drift from.
3. **Tests:** triage the 10 non-importing files (rename/rewrite vs. delete);
   the priority read is whether `test_frontend_bindings.py`'s 85 tests are
   salvageable. Fix the 14 stale-assertion failures once the generators are green.
4. **Docs:** rewrite the authored set (getting-started, concepts, tutorials, api)
   onto the current API; decide keep-as-history vs. delete for the 14 proposals;
   regenerate `reference/` indexes.
5. **Skills:** find/replace the old package paths and "session" vocabulary; verify
   each audit skill runs against the repaired tooling.
6. **Scratch hygiene:** delete the 272M stray log and the 3 tracked junk artifacts;
   keep `value_change_refactor/` and the two review `.md`s.

The examples need essentially nothing beyond the BOM strip — they can anchor the
docs rewrite as the source of truth for current API usage.

---

## 9. Harness strategy: surviving the next large refactor

The deeper lesson from this drift is not "the docs/tests/skills were neglected."
It is that **the harness asserted the *shape of the implementation* — symbol
names, module paths, app-spec types, frozen index contents — instead of the
*behavior a user depends on*.** A refactor renames the shapes, so everything goes
red at once, even when nothing a user cares about changed.

The proof is in this very review: **examples were the only healthy tree, and for
exactly one reason — they are executable and had to keep working.** That is the
whole strategy in one observation.

### Principle

Anchor the harness to **executable truth and behavioral invariants**, and
**explicitly segregate the implementation-coupled parts as disposable-by-design.**
The goal is *not* to make everything refactor-proof (brittle unit tests are
valuable *between* refactors). It is to make it obvious which tier is load-bearing
and which is expected to churn, so a large refactor becomes "keep tier 0 green,
regenerate/rewrite tier 2" instead of "everything is broken — is that bad?"

### Three tiers by coupling to implementation

**Tier 0 — survives almost any refactor. Small, hand-maintained, load-bearing.**
- *Tests:* characterization / golden tests that run the **real examples** and
  fingerprint *observable behavior* — "this authoring script yields a morphology
  panel + a voltage trace + this sequence of field updates," not "the object is a
  `MorphologyViewSpec` with `field_id=X`." The `scratch/value_change_refactor/`
  harness (golden.py / runtime_golden.py) is the seed of this; it needs to move
  into `tests/` and fingerprint user-visible output rather than internal types.
- *Docs:* concept / narrative docs — the field model, why actors, the update
  protocol, tutorials, getting-started. They carry understanding and age slowly
  because they don't name call signatures.
- *Skills:* thin procedures that tell an agent **how to re-derive current truth**,
  not what it is today — e.g. "backends live under `backends/<name>/`; mirror the
  neuron backend's structure; validate with `examples/neuron/*.py`." Survives a
  rename because it points at an exemplar and a search, not at frozen structure.

**Tier 2 — expected to churn in a refactor. Cheap or generated. Marked as such.**
- *Tests:* unit tests of internal structure (e.g. the 85 frontend-binding tests).
  Keep them for day-to-day work, but tag them `implementation-coupled` so a
  refactor can knowingly quarantine them.
- *Docs:* API **reference** — generated, never hand-authored and never asserted
  byte-for-byte (see below).
- *Skills:* deep architecture-encoding skills. Useful, but snapshots.

### The reference vs. narrative distinction (what "generated docs" means)

"Generate the reference docs" does **not** mean "put all docs in the code." There
are two kinds of documentation with opposite failure modes, and only one is
generated:

| | Reference | Narrative |
|---|---|---|
| **What** | What exists: exports, signatures, params, the per-symbol "this does X" | Why it exists: field model, why actors, how to build a session, getting-started |
| **Source of truth** | the code | a human's understanding |
| **Home** | docstrings + generated index | hand-authored `.md` in `docs/` |
| **Ages** | automatically (moves with the code) | slowly (doesn't name signatures) |

Only the **reference** column is generated / embedded in code, and it is generated
two ways:
1. **The index** (what's exported, grouped by area) is generated by walking
   `__all__` — nobody hand-maintains a list of symbol names. This is what stops
   `api/public-api.md` from naming `build_replay_app` two months after deletion.
2. **The per-symbol prose** (one paragraph, "what this does") lives in the
   **docstring**; the reference page pulls it from there. The signature comes from
   the code automatically; the description sits next to the thing it describes.

Point 2 is why it is refactor-resilient — the same reason the examples survived:
**proximity to executable truth.** You cannot move a function without its docstring
coming along, and a changed parameter surfaces the stale docstring in the *same
diff* the reviewer is already reading. A hand-authored `api/public-api.md` has no
such gravity; it drifts silently until a meta-test yells.

The **narrative** column — where most of the human value lives — stays authored
markdown and is *never* generated. The old setup's mistake was not that docs were
authored; it is that the **reference** was authored, then frozen and asserted, so
it rotted the instant a name changed.

### Mechanisms that make the tiers hold

1. **Executability is the enforcement.** Tie docs and skills *to the examples*:
   narrative docs quote real example code (extracted and tested, so a broken quote
   fails), skills name examples as templates, golden tests run the examples. When
   examples pass, the harness is pinned to reality — and examples pass because they
   are run.
2. **Generate, don't assert.** Anything derivable from code (indexes, symbol lists,
   repo map, reference pages) is regenerated, not compared to a checked-in copy. If
   it must be committed for browsing, the check is "regenerate is a no-op," not
   "matches this frozen blob."
3. **Golden as refactor scaffolding.** The workflow becomes: capture golden
   behavior of the examples → refactor freely, letting tier-2 unit tests break →
   keep golden green → rewrite tier-2 to the new structure afterward. The golden is
   what lets you *throw away* the brittle tier safely. The flexibility for large
   refactors comes from having a behavioral net under you, not from making
   everything refactor-proof.

### The tradeoff (stated honestly)

Tier 0 is more work to write well — a behavioral fingerprint takes more thought
than `assert x == MorphologyViewSpec`, and it is a deliberately smaller set. But it
is the set that is still true after the internals are gutted, which is the entire
point.

### Suggested sequence

Build the net first, then clean under its protection:
1. Promote the `value_change_refactor` golden harness into `tests/` as the tier-0
   anchor, retargeted at *example behavior*.
2. Make the reference docs + `reference/` indexes generated-only; move per-symbol
   prose into docstrings.
3. Rewrite skills as exemplar-pointing procedures.

This gives the refactor net before the rest of the alpha burn-down (§8) happens.
