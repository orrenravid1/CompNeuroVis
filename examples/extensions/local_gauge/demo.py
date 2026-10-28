"""Run a widget made from two adjacent scripts and one CompNeuroVis install."""

from __future__ import annotations

import numpy as np

import compneurovis as cnv
from local_gauge import LocalGauge

source = cnv.source()
gauge = source.add(LocalGauge("App-local gauge", np.linspace(0.0, 1.0, 100)))
cnv.layout(((gauge,),))
cnv.show()
