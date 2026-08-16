# Standing coding principles

These are mandatory guardrails for this work, not retrospective review criteria.

1. **No widget privileged / first-class parity.** Built-in and third-party use one
   registry and one path; a built-in is a registered kind, not a blessed type. Do
   not dispatch with `isinstance` or closed type ladders. Shared machinery must not
   be named "builtin" or "extension" when it serves every registration.

2. **A widget is add/removable by touching only its own roughly one to three files.**
   Do not edit the frontend refresh loop, planner tables, or core kind constants.
   Search the new widget name, kind, and types across the tree: every hit outside
   its component, explicit composition root, tests, examples, or documentation is a
   possible privilege leak.

3. **Compose, do not bundle: one component, one job.** Producer to consumer through
   generic interfaces; output is plain data, not shaped for one specific consumer.

4. **No junk drawer.** Group by positive cohesion: the module is one nameable job.
   Do not group by residual labels such as `misc`, `utils`, `adapters`, or
   `leftovers`. Size is not the criterion. Before adding code, name the module's one
   job as a positive noun.

5. **Base over reuse-inheritance.** No false is-a relationships. When concrete
   implementations share a true contract, extract a shared base and make them
   siblings. Never inherit one concrete implementation from another merely to
   reuse code.

6. **Principled, not heuristic.** No band-aids. A fix must hold across the full
   configuration matrix, not only the current example. Name a temporary hack as
   such. Prefer relocating a concern to its owner over adding another special case.

7. **Core layering is strict.** Core never imports backends or frontends, even
   lazily. Inline authoring remains frontend-neutral. Kind strings plus registries
   are the seam between neutral authoring and a concrete frontend.

8. **Inline means no inheritance for user models.** A user's model stays a plain
   object handed to `cnv.*`; controls, recorders, and clicks use shared vocabulary.
   This does not prohibit legitimate library extension points such as the `Widget`
   ABC or backend bases used by low-level `RunSpec` authors.

9. **Widgets atomic, apps compose.** One widget owns one panel. Compose a complex
   interface from widgets, operators, contributions, and `cnv.layout`; do not make
   a library-level mega-widget. A local user class may wrap an app composition for
   reuse.

10. **Right-size complexity to context.** Do not carry library-grade abstraction
    into scratch or notebook code. Begin with the simplest honest data shape and
    add structure only when a concrete requirement demands it.

11. **Every layer does exactly its job: no more and no less.** Audit a feature as
    a complete vertical slice. Each layer must own only the facts and decisions
    required at that boundary: native adapters observe, renderers hit-test,
    frontend routers arbitrate immediate input, canonical messages describe
    portable intent, runtimes route, backends apply application policy, and
    authoring APIs lower convenient declarations. A passing end-to-end example is
    not enough if one layer quietly answers another layer's question. Conversely,
    do not leave a necessary responsibility implicit between layers.

12. **Generic foundation, specialized convenience.** Domain-specific operations
    such as entity selection or morphology painting may be thin compositions over
    generic hit, input, state, and routing contracts. They must not become the
    canonical machinery that every future surface, point cloud, editor tool, or
    frontend has to imitate. Test the abstraction by asking whether a new semantic
    value needs only registration/composition or another parallel infrastructure.

13. **Capabilities are orthogonal until explicitly connected.** Clicking does not
    imply selection; selection does not imply highlighting; geometry does not
    imply a view; a view does not imply a camera; backend ownership does not imply
    presentation. Express each connection in the authored application. Avoid
    incidental updates to unrelated traces, controls, selections, or visuals.

14. **No hidden privilege, including behavioral privilege.** The registry rule
    applies beyond widgets and renderers. Cameras, controls, overlays, hit result
    kinds, pointer tools, action modes, selection behavior, and presentation
    effects must not acquire special dispatch merely because they were implemented
    first. A default is a replaceable sibling selected by policy, not an exception
    embedded in the host loop.

15. **Put policy with the owner of the consequence.** A renderer may report what
    was hit but must not decide application selection policy. A frontend may own
    local focus, capture, and camera fallback but must not silently consume a
    portable application command. A backend or explicit controller owns domain
    mutation. An operator consumes inputs and contributes its own result or
    presentation; its consumer should not make room through special knowledge of
    that operator.

16. **Use the replacement test.** For every seam, ask what changes if Vispy is
    replaced by Three.js or Unity, NEURON by Jaxley or a custom backend, a local
    pipe by a remote transport, or one actor by many. Only the adapter or policy
    owner for that dimension should change. Python objects, GUI toolkit events,
    renderer primitives, and process-local callbacks must not cross canonical
    data boundaries. Recheck the app configuration matrix after architectural
    changes.

17. **Public ease must lower to the real architecture.** Dynamic source methods,
    inline helpers, and first-party conveniences are welcome, but they must produce
    the same scoped, data-only specs and commands available to third parties and
    low-level authors. Do not create a convenient bypass that works only for the
    built-in backend/frontend pair.

18. **Prefer one explicit composition root over distributed mutation.** Registration
    and assembly should be visible in the smallest reasonable composition root.
    Avoid import-time side effects, deletion tricks, magic names, or host-loop
    mutation spread across unrelated files. App fragments remain intentional:
    independently authored sources may contribute in parallel and are composed by
    scoped references rather than collapsed into one privileged source.

19. **Diagnose behavior from concrete observations first.** When a runnable path
    exists, add narrow logging at the boundaries relevant to the failure and ask
    the user to reproduce it before reading broadly or redesigning anything.
    Distinguish observed facts from hypotheses, and let event, value, routing,
    and rendering logs identify which layer failed. Read wider only when the
    observations cannot isolate the fault, and remove temporary diagnostic noise
    once the behavior is verified.

Workflow rule: inspect `git status` and recent history before offering to commit;
preserve unrelated user changes and remove obsolete paths instead of adding
pre-1.0 compatibility layers.
