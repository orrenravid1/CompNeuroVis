"""Stable name and identifier helpers for inline authoring."""

from keyword import iskeyword


def slug(value: str) -> str:
    """Normalize a user-facing name for generated spec identifiers."""
    normalized = "".join(
        character if character.isalnum() else "_"
        for character in str(value).strip()
    )
    return normalized.strip("_").lower() or "item"


def authoring_method_name(value: object, *, label: str) -> str:
    """Validate a name that will be exposed through Python attribute syntax."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if value != value.strip():
        raise ValueError(f"{label} cannot contain surrounding whitespace")
    if not value:
        raise ValueError(f"{label} cannot be empty")
    if value.startswith("_") or not value.isidentifier() or iskeyword(value):
        raise ValueError(
            f"{label} must be a public Python identifier usable as an attribute"
        )
    return value


__all__ = ["authoring_method_name", "slug"]
