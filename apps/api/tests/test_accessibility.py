"""Display and accessibility preferences: defaults, partial updates, validation, per-user scope and audit."""

import psycopg
from psycopg.rows import dict_row

from bioverse.db.seed import U_HADDAD
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, as_user

URL = "/api/accessibility/preferences"


def test_defaults_before_anything_is_saved(client):
    r = client.get(URL, headers=MAYA)
    assert r.status_code == 200
    body = r.json()
    assert body == {"senior_mode": False, "text_scale": 1.0, "high_contrast": False, "reduce_motion": False,
                    "read_aloud": False, "updated_at": None, "saved": False}


def test_save_and_partial_update(client):
    r = client.put(URL, headers=MAYA, json={"senior_mode": True, "text_scale": 1.3})
    assert r.status_code == 200, r.text
    assert r.json()["senior_mode"] is True and r.json()["text_scale"] == 1.3 and r.json()["saved"] is True
    # Only what's sent changes.
    r = client.put(URL, headers=MAYA, json={"read_aloud": True})
    body = r.json()
    assert body["senior_mode"] is True and body["text_scale"] == 1.3 and body["read_aloud"] is True
    assert client.get(URL, headers=MAYA).json()["read_aloud"] is True
    r = client.put(URL, headers=MAYA, json={"senior_mode": False, "high_contrast": True, "reduce_motion": True})
    body = r.json()
    assert (body["senior_mode"], body["high_contrast"], body["reduce_motion"]) == (False, True, True)


def test_validation(client):
    for bad in ({"text_scale": 0.9}, {"text_scale": 1.7}, {"text_scale": "big"}, {"senior_mode": "yes"},
                {"senior_mode": 1}, {"font": "large"}):
        assert client.put(URL, headers=MAYA, json=bad).status_code == 422, bad
    for ok in (1.0, 1.6, 1.15):
        assert client.put(URL, headers=MAYA, json={"text_scale": ok}).json()["text_scale"] == ok


def test_every_role_has_its_own_preferences(client):
    client.put(URL, headers=MAYA, json={"senior_mode": True})
    for headers in (OKAFOR, ADMIN):
        assert client.get(URL, headers=headers).json()["senior_mode"] is False
        assert client.put(URL, headers=headers, json={"high_contrast": True}).status_code == 200
    assert client.get(URL, headers=MAYA).json()["high_contrast"] is False
    assert client.get(URL).status_code == 401


def test_seeded_senior_mode_demo_user(client):
    body = client.get(URL, headers=as_user(U_HADDAD)).json()
    assert body["senior_mode"] is True and body["text_scale"] == 1.2
    users = client.get("/api/session/demo-users").json()
    assert any(u["id"] == U_HADDAD and u["subtitle"] == "Patient, senior mode" for u in users)


def test_updates_are_audited(client):
    client.put(URL, headers=MAYA, json={"senior_mode": True, "text_scale": 1.2})
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        event = conn.execute(
            "SELECT patient_id::text, detail FROM audit_events WHERE action = 'ui_preferences_updated'"
        ).fetchone()
    assert event["patient_id"] == P_MAYA and event["detail"]["changed"] == ["senior_mode", "text_scale"]
