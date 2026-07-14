---
name: scratch-exploration
description: Build a disposable script or notebook to validate one assumption before changing source.
---

# Scratch Exploration

Use scratch/ for disposable scripts and notebooks.

- State one question at top of file.
- Keep setup local and explicit.
- Use current public source API unless probing lower layer itself.
- Do not add scratch files to tests, docs, indexes, or package exports.
- Move a useful result into examples/ or src/. Otherwise delete it.
