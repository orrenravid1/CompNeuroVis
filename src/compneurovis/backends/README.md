---
title: Backends Package
summary: Simulator backend actors, shared runtime behavior, and source adapters.
---

# Backends Package

`compneurovis.backends` contains simulator-specific integrations. Current live backends are:

- `neuron`
- `jaxley`

Simulator-specific stepping, collection, geometry conversion, IO, layout, and
source authoring stay inside the owning backend package. Shared history and
interaction behavior lives directly under `compneurovis.backends` or its
`compartment` package; generic widgets do not move into simulator packages.
