"""Critical-path unit tests for app/core/gstin.py.

Covers mod-36 checksum, PAN cross-check, state-code extraction, and
invalid-input rejection.
"""

from __future__ import annotations

import pytest
from app.core.gstin import (
    gstin_state_code,
    pan_from_gstin,
    validate_gstin,
    validate_pan,
)

from tests.gstin_fixtures import gstin_checksum_valid, make_gstin, make_pan


def test_validate_gstin_accepts_valid_fixture() -> None:
    gstin = make_gstin(state_code="29")
    assert validate_gstin(gstin) == gstin.upper()


def test_validate_gstin_rejects_bad_checksum() -> None:
    good = make_gstin()
    bad = good[:14] + ("0" if good[14] != "0" else "1")
    assert not gstin_checksum_valid(bad)
    with pytest.raises(ValueError, match="invalid GSTIN checksum"):
        validate_gstin(bad)


def test_validate_gstin_rejects_short_input() -> None:
    with pytest.raises(ValueError, match="invalid GSTIN format"):
        validate_gstin("27AAPFU0939F1Z")


def test_validate_gstin_pan_mismatch() -> None:
    gstin = make_gstin()
    wrong_pan = make_pan()
    with pytest.raises(ValueError, match="PAN does not match GSTIN"):
        validate_gstin(gstin, pan=wrong_pan)


def test_pan_and_state_from_gstin() -> None:
    pan = make_pan()
    gstin = make_gstin(pan=pan, state_code="07")
    assert pan_from_gstin(gstin) == pan
    assert gstin_state_code(gstin) == "07"


def test_validate_pan() -> None:
    assert validate_pan("AAAPZ1234C") == "AAAPZ1234C"
    with pytest.raises(ValueError, match="invalid PAN format"):
        validate_pan("1234567890")
