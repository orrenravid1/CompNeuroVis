---
title: Proposals
summary: Detailed design documents for specific subsystem changes not yet implemented.
---

# Proposals

Each proposal covers a specific feature or subsystem change in enough detail to
inform implementation. Proposals are not settled decisions. When a proposal is
implemented, the durable lessons move to [Design Decisions](../decisions.md).

- [Layout Workbench](layout-workbench-proposal.md) - replace the transitional panel grid with a recursive split-tree model and uniform panel identity.
- [Runtime Panel Layout Updates](panel-layout-updates.md) - `PanelPatch` and `LayoutReplace` for session-driven panel changes without full scene rebuild.
- [WebSocket Transport](websocket-transport-proposal.md) - add a WebSocket transport to support WSL backends, Windows frontends, and future non-Python clients.
- [Backend, Transport, and Frontend Abstractions](backend-transport-frontend-proposal.md) - rename and clarify the runtime core around explicit backend, transport, frontend, and thin typed message contracts, with resource-state and capability packaging staged as later extensions.
- [Composable Authoring Proof](composable-authoring-proof.md) - prove that current examples can lower into a class-light feature-composable authoring surface over the same backend, transport, frontend, message, and AppSpec runtime.
- [Canvas Backend and Rendering State](canvas-backend-rendering-state-2026-06-17.md) - record the current VisPy/Qt canvas, swap-interval, refresh-budget, and alternate-backend investigation for live rendering performance.
