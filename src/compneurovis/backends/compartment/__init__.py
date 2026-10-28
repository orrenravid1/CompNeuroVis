"""Shared runtime behavior for compartment simulators."""

from .history import CompartmentHistoryMixin, resolved_field_max_samples

__all__ = ["CompartmentHistoryMixin", "resolved_field_max_samples"]
