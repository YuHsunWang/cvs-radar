"""Compatibility wrapper for the package scoring module.

The real implementation lives in :mod:`cvs_radar.scoring`; this file is kept
because the original project exposed a root-level ``scoring.py``.
"""

from cvs_radar.scoring import *  # noqa: F401,F403
