"""Synthetic GSTIN/PAN fixture helpers (AI_BUILD_PLAYBOOK hard rule #1).

Generated GSTINs are structurally valid and pass the mod-36 checksum digit
(same algorithm as scripts/measure_extraction.py and app/core/gstin.py); the
PAN is embedded at GSTIN[2:12] so PAN cross-checks hold. Randomized per call
so shared-DB test runs never collide on unique columns. These are FIXTURE
identities only — never ship them as real taxpayer data.
"""

from __future__ import annotations

from app.core.gstin import (
    gstin_checksum_valid,
    make_gstin,
    make_pan,
    validate_gstin,
)

__all__ = ["make_gstin", "make_pan", "validate_gstin", "gstin_checksum_valid"]
