"""Browser keyboard adapter for the toolkit-neutral keyboard foundation."""

from __future__ import annotations

from collections.abc import Callable

import anywidget
import traitlets

from compneurovis.core.keyboard import KeySample


_ESM = r"""
function render({ model, el }) {
  el.style.display = "none";
  let active = false;
  let sequence = 0;
  const claimedKeys = new Set();

  function targetIsEditable(target) {
    if (!(target instanceof Element)) return false;
    return Boolean(target.closest(
      "input, textarea, select, [contenteditable='true']"
    ));
  }

  function targetOwnsActivationKey(event) {
    if (!(event.target instanceof Element)) return false;
    const button = event.target.closest("button");
    return Boolean(button && (event.key === " " || event.key === "Enter"));
  }

  function signature(event) {
    const modifiers = [];
    if (event.ctrlKey) modifiers.push("control");
    if (event.altKey) modifiers.push("alt");
    if (event.shiftKey) modifiers.push("shift");
    if (event.metaKey) modifiers.push("meta");
    let key = event.key === " " ? "space" : event.key.toLowerCase();
    return [...modifiers, key].join("+");
  }

  function keyIdentity(event) {
    return event.code || event.key.toLowerCase();
  }

  function emit(event, phase) {
    sequence += 1;
    model.set("_key_event", {
      sequence,
      phase,
      key: event.key === " " ? "Space" : event.key,
      physical_key: event.code || null,
      modifiers: [
        ...(event.ctrlKey ? ["control"] : []),
        ...(event.altKey ? ["alt"] : []),
        ...(event.shiftKey ? ["shift"] : []),
        ...(event.metaKey ? ["meta"] : []),
      ],
      repeat: Boolean(event.repeat),
      timestamp: event.timeStamp / 1000.0,
    });
    model.save_changes();
  }

  function onPointerDown(event) {
    const root = el.closest(".compneurovis-notebook-app");
    active = Boolean(root && root.contains(event.target));
    if (!active) claimedKeys.clear();
  }

  function onKeyDown(event) {
    if (
      !active
      || targetIsEditable(event.target)
      || targetOwnsActivationKey(event)
    ) return;
    const shortcuts = new Set(model.get("shortcut_signatures") || []);
    const identity = keyIdentity(event);
    if (!claimedKeys.has(identity) && !shortcuts.has(signature(event))) return;
    claimedKeys.add(identity);
    event.preventDefault();
    emit(event, "press");
  }

  function onKeyUp(event) {
    const identity = keyIdentity(event);
    if (!claimedKeys.delete(identity)) return;
    event.preventDefault();
    emit(event, "release");
  }

  document.addEventListener("pointerdown", onPointerDown, true);
  document.addEventListener("keydown", onKeyDown, true);
  document.addEventListener("keyup", onKeyUp, true);

  return () => {
    document.removeEventListener("pointerdown", onPointerDown, true);
    document.removeEventListener("keydown", onKeyDown, true);
    document.removeEventListener("keyup", onKeyUp, true);
  };
}
export default { render };
"""


class NotebookKeyboardWidget(anywidget.AnyWidget):
    """Translate browser key events into neutral samples for one notebook app."""

    _esm = _ESM
    shortcut_signatures = traitlets.List(traitlets.Unicode()).tag(sync=True)
    _key_event = traitlets.Dict(default_value={}).tag(sync=True)

    def __init__(
        self,
        callback: Callable[[KeySample], None],
        **kwargs,
    ) -> None:
        if not callable(callback):
            raise TypeError("Notebook keyboard callback must be callable")
        super().__init__(**kwargs)
        self._callback = callback
        self.observe(self._on_key_event, names="_key_event")

    def _on_key_event(self, change) -> None:
        event = dict(change.get("new") or {})
        if not event:
            return
        self._callback(
            KeySample(
                phase=str(event["phase"]),
                key=str(event["key"]),
                physical_key=event.get("physical_key"),
                modifiers=tuple(event.get("modifiers", ())),
                repeat=bool(event.get("repeat", False)),
                timestamp=event.get("timestamp"),
            )
        )


__all__ = ["NotebookKeyboardWidget"]
