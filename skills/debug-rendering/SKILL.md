---
name: debug-rendering
description: Debug blank, incorrect, delayed, or slow VisPy panels after dataflow is confirmed.
---

# Debug Rendering

Treat current src/compneurovis/frontends/vispy/ as authority.

Debug in this order:

1. Confirm latest data exists in frontend projection.
2. Confirm view resolves correct scoped data, geometry, controls, and operators.
3. Confirm refresh planner schedules only required panel work.
4. Inspect panel adapter and visual with smallest static example.
5. For morphology, verify geometry array lengths, nonzero radii, camera framing,
   color-value length, and selection mapping.
6. For surfaces, verify value shape matches coordinate order and color limits.
7. For lines and bars, verify series shape, x values, history window, and axis
   limits.
8. For freezes, log receive, projection, refresh planning, draw, paint, and event
   loop gaps separately. Bound stale queued work before reducing visual quality.

Use current logging framework. Do not infer renderer failure until dataflow and
refresh targeting are proven.
