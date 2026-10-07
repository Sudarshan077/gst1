"""Task 0.5 — cross-tenant access matrix + audit logging (SECURITY §2/§5, v4).

Every actor class x every target must yield either clean access or a 404/403
envelope that carries ZERO GSTIN data. 404 over 403 — existence is data
(API_SPEC non-negotiable #2). Audit rows are append-only, proven by live
UPDATE/DELETE failures against the restricted `gst_app` role.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.core import access as access_mod
from app.core.auth.tokens import verify_access_token
from app.core.gst_accounts import service as gstin_service
from app.db.models.core import AccessRole, AuditLog, User
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.auth_helpers import make_email, register_and_login
from tests.gstin_fixtures import gstin_checksum_valid, make_gstin, make_pan
from tests.v4_helpers import guard_app, seed_account

pytestmark = pytest.mark.asyncio

SessionMaker = async_sessionmaker[Any]


# --------------------------------------------------- fixture GSTIN sanity


async def test_fixture_gstin_passes_mod36_and_pan_embedding() -> None:
    for _ in range(25):
        pan = make_pan()
        g = make_gstin(pan=pan)
        assert gstin_checksum_valid(g)
        assert g[2:12] == pan


async def test_gstin_service_derives_pan_and_state_from_gstin(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """v4: the caller never supplies a PAN — it is GSTIN[2:12]."""
    gstin = make_gstin(state_code="29")
    tokens = await register_and_login(client, make_email())
    user_id = verify_access_token(tokens["access_token"])
    async with api_sessionmaker() as session:
        account = await gstin_service.create_gst_account(
            session, gstin=gstin, legal_name="Derived Co", created_by=user_id
        )
    assert account.pan == gstin[2:12]
    assert account.state_code == "29"
    assert account.gstin == gstin


async def test_invalid_gstin_checksum_rejected(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    from app.api.errors import ServiceError

    good = make_gstin()
    bad = good[:14] + ("0" if good[14] != "0" else "1")
    tokens = await register_and_login(client, make_email())
    user_id = verify_access_token(tokens["access_token"])
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await gstin_service.create_gst_account(
                session, gstin=bad, legal_name="Bad Co", created_by=user_id
            )
    assert exc.value.status_code == 422


# ------------------------------------------------------- cross-tenant MATRIX
# Actor classes: ADMIN(owner), FILER(collaborator), VIEWER(collaborator),
#                outsider (no grants).
# Targets: own GSTIN, the user's second GSTIN, another user's GSTIN,
#          a revoked grant, a nonexistent GSTIN.
# Grant -> 200 with data; everything else -> 404/403 envelope, zero data.


def _row(
    label: str, token: str, path: str, ident: Any, expect: int, code: str = ""
) -> dict[str, Any]:
    return {
        "label": label,
        "token": token,
        "path": path,
        "ident": ident,
        "expect": expect,
        "code": code,
    }


async def test_cross_tenant_matrix(
    client: AsyncClient,
    api_sessionmaker: SessionMaker,
) -> None:
    owner_tokens, owner_account = await seed_account(
        client, api_sessionmaker, legal_name="Tenant A Pvt Ltd"
    )
    owner_id = verify_access_token(owner_tokens["access_token"])

    other_tokens, _other_account = await seed_account(
        client, api_sessionmaker, legal_name="Tenant B Pvt Ltd"
    )

    # FILER and VIEWER collaborators on the owner's GSTIN.
    filer_tokens = await register_and_login(client, make_email())
    filer_id = verify_access_token(filer_tokens["access_token"])
    viewer_tokens = await register_and_login(client, make_email())
    viewer_id = verify_access_token(viewer_tokens["access_token"])

    async with api_sessionmaker() as session:
        filer_email = f"filer+{uuid.uuid4().hex[:8]}@example.com"
        viewer_email = f"viewer+{uuid.uuid4().hex[:8]}@example.com"
        filer_user = await session.get(User, filer_id)
        viewer_user = await session.get(User, viewer_id)
        assert filer_user is not None and viewer_user is not None
        filer_user.email = filer_email
        viewer_user.email = viewer_email
        await session.commit()

        await gstin_service.add_collaborator(
            session,
            owner_account.gstin,
            email=filer_email,
            role=AccessRole.FILER,
            actor_user_id=owner_id,
        )
        await gstin_service.add_collaborator(
            session,
            owner_account.gstin,
            email=viewer_email,
            role=AccessRole.VIEWER,
            actor_user_id=owner_id,
        )

    # A second GSTIN owned by the outsider, to prove independence of grants.
    second_owner_tokens, second_owner_account = await seed_account(
        client, api_sessionmaker, legal_name="Second Owner Pvt Ltd"
    )

    # A GSTIN granted then revoked for the filer.
    revoked_tokens, revoked_account = await seed_account(
        client, api_sessionmaker, legal_name="Revoked Target Pvt Ltd"
    )
    revoked_owner_id = verify_access_token(revoked_tokens["access_token"])
    async with api_sessionmaker() as session:
        filer_user = await session.get(User, filer_id)
        assert filer_user is not None
        await gstin_service.add_collaborator(
            session,
            revoked_account.gstin,
            email=filer_user.email or "",
            role=AccessRole.VIEWER,
            actor_user_id=revoked_owner_id,
        )
        await gstin_service.revoke_collaborator(
            session,
            revoked_account.gstin,
            target_user_id=filer_id,
            role=AccessRole.ADMIN,
            actor_user_id=revoked_owner_id,
        )

    fake = make_gstin()
    tk_admin, tk_filer, tk_viewer = (
        owner_tokens["access_token"],
        filer_tokens["access_token"],
        viewer_tokens["access_token"],
    )
    tk_out = other_tokens["access_token"]
    tk_second_admin = second_owner_tokens["access_token"]

    base = "/api/v1/probe/gstin"
    probe = f"{base}/{owner_account.gstin}"
    probe_w = f"{probe}/write-probe"

    def _cases() -> list[dict[str, Any]]:
        """(label, actor token, target gstin, expected status, expected code)."""
        spec: list[tuple[str, str, str, int, str]] = [
            ("admin->own", tk_admin, owner_account.gstin, 200, ""),
            ("filer->own", tk_filer, owner_account.gstin, 200, ""),
            ("viewer->own", tk_viewer, owner_account.gstin, 200, ""),
            ("outsider->A", tk_out, owner_account.gstin, 404, "GSTIN_NOT_FOUND"),
            ("adminB->A", tk_second_admin, owner_account.gstin, 404, "GSTIN_NOT_FOUND"),
            ("adminB->ownB", tk_second_admin, second_owner_account.gstin, 200, ""),
            ("outsider->ownB", tk_out, second_owner_account.gstin, 404, "GSTIN_NOT_FOUND"),
            ("filer->revoked", tk_filer, revoked_account.gstin, 404, "GSTIN_NOT_FOUND"),
            ("outsider->nonexistent", tk_out, fake, 404, "GSTIN_NOT_FOUND"),
            ("admin->nonexistent", tk_admin, fake, 404, "GSTIN_NOT_FOUND"),
        ]
        rows = [
            _row(label, token, f"{base}/{target}", target, status, code)
            for label, token, target, status, code in spec
        ]
        # view/write role split on one GSTIN: VIEWER 403, FILER/ADMIN 200.
        rows.append(_row("viewer->write-probe", tk_viewer, probe_w, owner_account.gstin, 403))
        rows.append(_row("filer->write-probe", tk_filer, probe_w, owner_account.gstin, 200))
        rows.append(_row("admin->write-probe", tk_admin, probe_w, owner_account.gstin, 200))
        return rows

    rows = _cases()

    checked = 0
    app = guard_app(api_sessionmaker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for row in rows:
            resp = await ac.get(
                row["path"], headers={"Authorization": f"Bearer {row['token']}"}
            )
            checked += 1
            body: dict[str, Any] = {}
            try:
                body = resp.json()
            except Exception:
                body = {}
            dumped = str(body)
            assert resp.status_code == row["expect"], (
                f"{row['label']}: {resp.status_code} {resp.text}"
            )
            if row["expect"] == 200:
                assert body.get("success") is True, f"{row['label']}: envelope"
                assert body.get("data"), f"{row['label']}: must carry data"
            else:
                assert row["code"] in dumped, f"{row['label']}: {body}"
                # zero leaked tenant data
                assert "Tenant A" not in dumped and "Tenant B" not in dumped, row["label"]
                assert owner_account.pan not in dumped, f"{row['label']}: PAN leak"
                assert second_owner_account.pan not in dumped, f"{row['label']}: PAN leak"
    assert checked == len(rows) == 13, f"matrix must exercise all rows, ran {checked}"


async def test_revoke_is_instant_access_death(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """Revoke = instant loss of access (SECURITY §4 — no cache, no TTL)."""
    owner_tokens, account = await seed_account(client, api_sessionmaker)
    owner_id = verify_access_token(owner_tokens["access_token"])

    collab_tokens = await register_and_login(client, make_email())
    collab_id = verify_access_token(collab_tokens["access_token"])
    email = f"collab+{uuid.uuid4().hex[:8]}@example.com"
    async with api_sessionmaker() as session:
        user = await session.get(User, collab_id)
        assert user is not None
        user.email = email
        await session.commit()
        await gstin_service.add_collaborator(
            session,
            account.gstin,
            email=email,
            role=AccessRole.FILER,
            actor_user_id=owner_id,
        )

    app = guard_app(api_sessionmaker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ok = await ac.get(
            f"/api/v1/probe/gstin/{account.gstin}",
            headers={"Authorization": f"Bearer {collab_tokens['access_token']}"},
        )
        assert ok.status_code == 200

        async with api_sessionmaker() as session:
            await gstin_service.revoke_collaborator(
                session,
                account.gstin,
                target_user_id=collab_id,
                role=AccessRole.ADMIN,
                actor_user_id=owner_id,
            )

        dead = await ac.get(
            f"/api/v1/probe/gstin/{account.gstin}",
            headers={"Authorization": f"Bearer {collab_tokens['access_token']}"},
        )
        assert dead.status_code == 404
        assert dead.json()["error"]["code"] == "GSTIN_NOT_FOUND"


async def test_last_admin_cannot_be_revoked(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    from app.api.errors import ServiceError

    owner_tokens, account = await seed_account(client, api_sessionmaker)
    owner_id = verify_access_token(owner_tokens["access_token"])
    async with api_sessionmaker() as session:
        with pytest.raises(ServiceError) as exc:
            await gstin_service.revoke_collaborator(
                session,
                account.gstin,
                target_user_id=owner_id,
                role=AccessRole.ADMIN,
                actor_user_id=owner_id,
            )
    assert exc.value.status_code == 409


# ----------------------------------------------------------------- audit


async def test_guard_denial_leaves_no_audit_row_and_grant_does(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """Attaching a GSTIN writes one audit row; a denied probe writes none."""
    owner_tokens, account = await seed_account(
        client, api_sessionmaker, legal_name="Audit Co"
    )
    owner_id = verify_access_token(owner_tokens["access_token"])
    outsider = await register_and_login(client, make_email())

    app = guard_app(api_sessionmaker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        denied = await ac.get(
            f"/api/v1/probe/gstin/{account.gstin}",
            headers={"Authorization": f"Bearer {outsider['access_token']}"},
        )
    assert denied.status_code == 404

    async with api_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.gstin == account.gstin)
                )
            )
            .scalars()
            .all()
        )
    actions = [r.action for r in rows]
    assert actions == ["GSTIN_ATTACHED"], actions
    assert rows[0].actor_user_id == owner_id
    assert rows[0].payload_diff == {"after": {"role": "ADMIN"}}


async def test_audit_logs_table_is_append_only(
    client: AsyncClient, api_sessionmaker: SessionMaker
) -> None:
    """UPDATE/DELETE on core.audit_logs must fail (SECURITY §5 DB-grant rule).

    Proven against the dedicated restricted role `gst_app` (migration
    a41c7e2d90f5 heritage, re-issued in the v4 migration): INSERT allowed,
    UPDATE/DELETE raise. The dev superuser `gst` bypasses grants, so the
    tamper attempts MUST run as gst_app.
    """
    import os

    import psycopg

    password = os.environ.get("GST_APP_ROLE_PASSWORD", "gst_app_dev_pass")
    app_url = f"postgresql://gst_app:{password}@127.0.0.1:5436/gst_filing_db"

    probe_id = uuid.uuid4().hex
    async with api_sessionmaker() as session:
        await access_mod.audit(
            session,
            action="PROBE_EVENT",
            entity="probe",
            entity_id=probe_id,
            actor_user_id=None,
        )
        await session.commit()

    with psycopg.connect(app_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO core.audit_logs (id, action, entity, entity_id) "
            "VALUES (gen_random_uuid(), 'PROBE_EVENT2', 'probe', %s)",
            (probe_id,),
        )
        conn.commit()

        try:
            cur.execute(
                "UPDATE core.audit_logs SET action = 'TAMPERED' WHERE entity_id = %s",
                (probe_id,),
            )
            conn.commit()
            tamper_update = False
        except psycopg.Error:
            conn.rollback()
            tamper_update = True
        assert tamper_update, "gst_app must NOT be able to UPDATE audit_logs"

        try:
            cur.execute(
                "DELETE FROM core.audit_logs WHERE entity_id = %s", (probe_id,)
            )
            conn.commit()
            tamper_delete = False
        except psycopg.Error:
            conn.rollback()
            tamper_delete = True
        assert tamper_delete, "gst_app must NOT be able to DELETE audit_logs"

    async with api_sessionmaker() as session:
        remaining = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.entity_id == probe_id)
                )
            )
            .scalars()
            .all()
        )
    assert sorted(r.action for r in remaining) == ["PROBE_EVENT", "PROBE_EVENT2"]
