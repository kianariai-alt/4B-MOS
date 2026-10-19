"""Configure the patient portal locally without printing encryption material."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil

from dotenv import dotenv_values
from backend.app.core.config import Settings


def configure(path: Path, *, origin: str, clinic_name: str):
    if not path.is_file():
        raise ValueError("Existing .env is required; configure the clinic application first.")
    values = dotenv_values(path)
    # Preserve the key across reruns; changing it would orphan stored requests.
    key = values.get("PATIENT_PORTAL_KEY")
    if not key:
        if "PATIENT_PORTAL_KEY" in values:
            raise ValueError("Existing portal key is empty; restore its backup before proceeding.")
        key = base64.b64encode(secrets.token_bytes(32)).decode()
    updates = {"PATIENT_PORTAL_ENABLED": True, "PATIENT_PORTAL_ORIGIN": origin,
        "PATIENT_PORTAL_NAME": clinic_name, "PATIENT_PORTAL_KEY": key}
    Settings(_env_file=path, **updates)  # Validate the full configuration before writing.
    old = path.read_text(encoding="utf-8")
    remaining = [line for line in old.splitlines() if not any(line.lstrip().startswith(name + "=") or line.lstrip().startswith(name + " =") for name in updates)]
    text = "\n".join(remaining).rstrip() + "\n"
    for name, value in updates.items():
        text += name + "=" + ("true" if value is True else json.dumps(value, ensure_ascii=False)) + "\n"
    backup = path.with_name(path.name + ".portal-backup.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
        backup.chmod(0o600)
    temporary = path.with_name(path.name + ".portal-setup.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8000")
    parser.add_argument("--name", default="کلینیک 4B")
    parser.add_argument("--qr", type=Path)
    args = parser.parse_args()
    try:
        if args.qr and not args.origin.startswith("https://"):
            parser.error("QR requires a public HTTPS origin; loopback is for PC testing only.")
        configure(Path(".env"), origin=args.origin, clinic_name=args.name)
        if args.qr:
            import qrcode
            if args.qr.exists():
                parser.error("QR output already exists; choose a new filename.")
            qrcode.make(args.origin + "/patient/").save(args.qr)
    except ValueError:
        parser.error("Configuration validation failed; check origin and restore any existing portal key. No secret is printed.")
    print("Patient portal configuration saved; existing portal key preserved.")
    print("Grant inbox access with backend.tools.portal_access, then restart the server.")
    print("Patient:", args.origin + "/patient/")
    print("Staff:", args.origin + "/app/portal-inbox.html")
    if not args.origin.startswith("https://"):
        print("Loopback test only: this address cannot be used by a patient's phone.")


if __name__ == "__main__":
    main()
