### 2026-05-25
- Still code smell in the PanelSpec due to having many fields that various panels don't use. Idk if kind is enough to break that down
- I'm still not sure exactly where the layout resolution lives. There's helpers, but where are they used? Like whent the AppProjection needs to resolve the layout does it need to do that or something?
- Also we should probably move from grid to the tree-based approach
