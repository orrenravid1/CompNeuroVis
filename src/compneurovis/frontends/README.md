---
title: Frontends Package
summary: Frontend actors that consume canonical AppSpec declarations and messages.
---

# Frontends Package

`compneurovis.frontends` hosts renderer-specific frontends. The current
implementation is `vispy`, and it consumes `AppSpec` as the frontend contract,
including any app-scoped `DiagnosticsSpec` settings.
