from __future__ import annotations

from willo_orchestrator.status import new_status


def test_new_status_starts_at_onboarding_with_nothing_else_set() -> None:
    status = new_status()

    assert status.as_json() == {
        "stage": "onboarding",
        "claimCode": None,
        "qrDataUrl": None,
        "deviceModel": None,
        "error": None,
    }


def test_as_json_reflects_mutations() -> None:
    status = new_status()

    status.stage = "awaiting-pairing"
    status.claim_code = "ABCD1234"
    status.device_model = "Green"

    assert status.as_json() == {
        "stage": "awaiting-pairing",
        "claimCode": "ABCD1234",
        "qrDataUrl": None,
        "deviceModel": "Green",
        "error": None,
    }
