"""Stable identifier helpers for inline authoring."""


def slug(value: str) -> str:
    """Normalize a user-facing name for generated spec identifiers."""
    normalized = "".join(
        character if character.isalnum() else "_"
        for character in str(value).strip()
    )
    return normalized.strip("_").lower() or "item"


__all__ = ["slug"]
