from __future__ import annotations

from app.config import get_settings


def test_gsp_irp_developer_tier_config() -> None:
    settings = get_settings()

    # Verify GSP sandbox free developer tier configuration
    assert settings.gsp_client_id is not None
    assert settings.gsp_client_secret is not None
    assert settings.gsp_username is not None
    assert settings.gsp_password is not None
    assert settings.gsp_sandbox_mode is True
    assert settings.gsp_api_base_url == "https://sandbox.gst.gov.in"

    # Verify IRP sandbox free developer tier configuration
    assert settings.irp_client_id is not None
    assert settings.irp_client_secret is not None
    assert settings.irp_username is not None
    assert settings.irp_password is not None
    assert settings.irp_sandbox_mode is True
    assert settings.irp_api_base_url == "https://einvoice1-trial.nic.in"
