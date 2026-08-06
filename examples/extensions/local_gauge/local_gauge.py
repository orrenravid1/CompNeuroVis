"""A widget authored as an ordinary adjacent script, with no extra install."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

import compneurovis as cnv
from compneurovis.frontends.vispy import register_vispy_plugin

# This records an import string only. The backend never imports Qt or Vispy.
register_vispy_plugin("local_gauge_vispy:register")


@dataclass(frozen=True, slots=True)
class LocalGauge(cnv.Widget):
    name: str
    values: Any

    def declare(self, context):
        data = context.data(
            "value",
            values=np.asarray(self.values, dtype=np.float32),
        )
        return context.view("local_gauge", self.name, inputs={"data": data})


__all__ = ["LocalGauge"]
