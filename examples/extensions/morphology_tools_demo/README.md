# App-local morphology tools

Run from the repository root:

~~~powershell
python examples/extensions/morphology_tools_demo/run.py
~~~

This is deliberately not a Python package. It demonstrates that an app-adjacent
widget can reuse `MorphologyRef.geometry`, add several independently colored
channels, own a resizable marker table, and bind tool behavior to the morphology's
exact click interaction.

- `select` lets the click fall through to normal selection and changes the trace.
- `paint` consumes the click and updates only the weight layer.
- `mark` consumes the click and adds a colored sphere without changing selection.

Painting is discrete per click. Continuous drag painting is intentionally not
simulated; it requires the future canonical pointer-event protocol described in
the widget architecture record.

## Isolated capabilities

- [`painting/`](painting/) contains the self-contained morphology-painting
  widget and runnable app. It does not depend on this combined demo.
