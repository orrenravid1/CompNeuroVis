from __future__ import annotations

from typing import TypeAlias

from compneurovis.core.runtime.channel import Channel


TransportEndpoint: TypeAlias = Channel
Transport: TypeAlias = TransportEndpoint

__all__ = ["Transport", "TransportEndpoint"]
