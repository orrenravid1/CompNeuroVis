from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields as dataclass_fields, is_dataclass
from typing import Any

from compneurovis.core.app_spec import AppRef, app_ref
from compneurovis.core.values import ValueBindingSpec


def resolve_binding(value, values: dict[Any, Any], fragment_id: str | None = None):
    """Resolve a value that may be a binding to its current value in ``values``.

    A ``ValueBindingSpec`` / ``AppRef`` resolves to the live value (fragment-scoped
    when possible); anything else is returned unchanged.
    """
    if isinstance(value, ValueBindingSpec):
        if fragment_id is not None:
            scoped = app_ref(value.key, fragment_id=fragment_id)
            if scoped in values:
                return values.get(scoped)
        return values.get(value.key)
    if isinstance(value, AppRef):
        if value in values:
            return values.get(value)
        return values.get(value.id, value)
    return value


def binding_key(value, fragment_id: str | None = None) -> str | AppRef | None:
    """The value-key a binding points at (fragment-scoped when given), else None."""
    if isinstance(value, ValueBindingSpec):
        return app_ref(value.key, fragment_id=fragment_id) if fragment_id is not None else value.key
    if isinstance(value, str) and fragment_id is not None:
        return app_ref(value, fragment_id=fragment_id)
    return value if isinstance(value, AppRef) else None


def _value_key_matches(local_key: str | AppRef | None, value_key: str | AppRef, fragment_id: str) -> bool:
    if local_key is None:
        return False
    scoped_key = app_ref(local_key, fragment_id=fragment_id)
    return value_key == local_key or value_key == scoped_key


def _binding_matches(value, value_key: str | AppRef, fragment_id: str) -> bool:
    key = binding_key(value)
    return key is not None and _value_key_matches(key, value_key, fragment_id)


def _contains_binding(value: Any, value_key: str | AppRef, fragment_id: str) -> bool:
    # A binding leaf (ValueBindingSpec / AppRef) is itself a dataclass, so match
    # it *before* the dataclass-descent branch -- otherwise we'd walk into its
    # raw ``key`` string instead of treating it as the binding it is.
    if _binding_matches(value, value_key, fragment_id):
        return True
    if isinstance(value, Mapping):
        return any(
            _contains_binding(item, value_key, fragment_id)
            for item in value.values()
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_binding(item, value_key, fragment_id) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        # Descend into dataclass-valued properties (e.g. reference-line markers,
        # whose ``value`` may itself be a binding) so a bound field nested in a
        # structured property still triggers a refresh -- generically, without
        # the caller knowing the dataclass's type.
        return any(
            _contains_binding(getattr(value, f.name), value_key, fragment_id)
            for f in dataclass_fields(value)
        )
    return False


def _ref(value: str | AppRef, fragment_id: str) -> AppRef:
    return app_ref(value, fragment_id=fragment_id)


def _optional_ref(value: str | AppRef | None, fragment_id: str) -> AppRef | None:
    if value is None:
        return None
    return app_ref(value, fragment_id=fragment_id)
