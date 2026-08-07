"""Public inline authoring API."""

# Define the widget contract and built-in classes before the composition root
# imports their factories. This avoids component import cycles while keeping
# registration explicit and centralized below.
from . import widgets as _widgets  # noqa: F401
from .builtins import register_first_party_inline

# Bootstrap before importing source facades: their static method reservation must
# see the first-party control/action names as intentional shared authoring names.
register_first_party_inline()

from .backend import InlineBackend  # noqa: E402
from .sampling import SeriesSampler  # noqa: E402
from .app import InlineApp  # noqa: E402
from .authoring import (  # noqa: E402
    _current_authoring_app as _current_authoring_app,
    _reset_authoring_app as _reset_authoring_app,
    compose,
    layout,
    remote,
    remote_actor,
    show,
    source,
)
from .sources import (  # noqa: E402
    ComposedSource,
    InlineSource,
    InlineSourceBase,
    RemoteActorRef,
    RemoteSource,
)

__all__ = [
    "ComposedSource",
    "InlineApp",
    "InlineBackend",
    "InlineSource",
    "InlineSourceBase",
    "RemoteActorRef",
    "RemoteSource",
    "SeriesSampler",
    "compose",
    "layout",
    "remote",
    "remote_actor",
    "show",
    "source",
]
