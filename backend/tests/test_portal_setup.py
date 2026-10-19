from dotenv import dotenv_values
import pytest
from backend.tools.portal_setup import configure


def test_setup_preserves_application_settings_and_existing_key(tmp_path):
    env = tmp_path / ".env"
    original = "# Existing configuration\nDATABASE_URL=sqlite:///test.db\nSECRET_KEY=unchanged-test-secret\n"
    env.write_text(original)
    configure(env, origin="http://127.0.0.1:8000", clinic_name="Synthetic clinic")
    first = dotenv_values(env)
    assert first["SECRET_KEY"] == "unchanged-test-secret"
    assert first["DATABASE_URL"] == "sqlite:///test.db"
    assert first["PATIENT_PORTAL_ENABLED"] == "true"
    configure(env, origin="https://patient.example", clinic_name='Synthetic "clinic"')
    second = dotenv_values(env)
    assert second["PATIENT_PORTAL_KEY"] == first["PATIENT_PORTAL_KEY"]
    assert second["PATIENT_PORTAL_NAME"] == 'Synthetic "clinic"'
    assert env.with_name(".env.portal-backup.bak").read_text() == original


def test_setup_does_not_change_config_on_invalid_origin(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=sqlite:///test.db\n")
    before = env.read_bytes()
    with pytest.raises(ValueError):
        configure(env, origin="http://public.example", clinic_name="Synthetic")
    assert env.read_bytes() == before
