# Morphology painting

Run from the repository root:

~~~powershell
python examples/extensions/morphology_tools_demo/painting/run.py
~~~

Enable **Paint instead of rotate**, press on a morphology segment, and drag over
other segments to paint them. A gesture that starts on empty background still
controls the camera. Disable paint mode to restore ordinary click selection and
camera rotation everywhere.

This example is self-contained and does not import the combined morphology-tools
demo. The painting widget has no renderer: it updates the morphology's exposed
color data, and the ordinary morphology renderer presents that field.

Painting is entity-level: the generic captured-pointer protocol reports each
segment crossed by the gesture, while the behavior widget decides how that
entity changes.
