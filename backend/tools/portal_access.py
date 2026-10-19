"""Trusted local management of the installation's patient-inbox access list."""
import argparse
from sqlalchemy import select
from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.models.patient_portal import PortalAccess
from backend.app.repositories.audit_log import AuditLogRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username.strip().lower()))
        if user is None or not user.is_active or user.role not in {"admin", "operator", "physician"}:
            parser.error("An active admin, operator or physician account is required.")
        grant = db.get(PortalAccess, user.id)
        if grant is None:
            grant = PortalAccess(user_id=user.id)
            db.add(grant)
        grant.active = not args.revoke
        AuditLogRepository.create(db, entity_type="portal_access", entity_id=user.id,
            event_type="local_access_revoked" if args.revoke else "local_access_granted", commit=False)
        db.commit()
        print("Patient inbox access:", "revoked" if args.revoke else "granted", "for", user.username)


if __name__ == "__main__":
    main()
