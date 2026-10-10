import pytest
from scripts import arena_signing as s


def test_signature_rejects_payload_tamper_wrong_purpose_and_revocation(tmp_path):
    envelope = s.sign_payload(tmp_path, {"result": 3}, "holdout-run")
    assert s.verify_payload(tmp_path, envelope, "holdout-run") == {"result": 3}
    with pytest.raises(ValueError):
        s.verify_payload(tmp_path, envelope, "manifest")
    envelope["payload"]["result"] = 4
    with pytest.raises(ValueError):
        s.verify_payload(tmp_path, envelope, "holdout-run")
    valid = s.sign_payload(tmp_path, {"result": 3}, "holdout-run")
    s.revoke_key(tmp_path, valid["key_id"])
    with pytest.raises(ValueError):
        s.verify_payload(tmp_path, valid, "holdout-run")


def test_rotation_and_untrusted_self_embedded_key(tmp_path):
    old = s.sign_payload(tmp_path, {}, "manifest")
    new_id = s.rotate_key(tmp_path)
    assert new_id != old["key_id"]
    assert s.verify_payload(tmp_path, old, "manifest") == {}
    other = tmp_path / "other"
    with pytest.raises(ValueError):
        s.verify_payload(other, old, "manifest")


def test_malformed_signature_fields_are_user_errors(tmp_path):
    envelope = s.sign_payload(tmp_path, {}, "manifest")
    envelope["key_id"] = []
    with pytest.raises(ValueError):
        s.verify_payload(tmp_path, envelope, "manifest")
