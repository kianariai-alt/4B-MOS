from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.orthobiologic_material import (
    OrthobiologicMaterial,
)
from backend.app.models.user import User
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.repositories.orthobiologic_material import (
    OrthobiologicMaterialRepository,
)
from backend.app.schemas.orthobiologic_material import (
    OrthobiologicMaterialCreate,
)
from backend.app.services.audit_context import (
    actor_data,
)


class OrthobiologicMaterialNotFoundError(
    Exception
):
    pass


class OrthobiologicMaterialCodeConflictError(
    Exception
):
    pass


class OrthobiologicMaterialService:
    @staticmethod
    def create_material(
        db: Session,
        payload: OrthobiologicMaterialCreate,
        actor: User | None = None,
    ) -> OrthobiologicMaterial:
        existing = (
            OrthobiologicMaterialRepository
            .get_by_code(
                db,
                payload.code,
            )
        )

        if existing is not None:
            raise (
                OrthobiologicMaterialCodeConflictError(
                    "Orthobiologic material "
                    f"'{payload.code}' "
                    "already exists."
                )
            )

        try:
            material = (
                OrthobiologicMaterialRepository
                .create(
                    db,
                    payload,
                )
            )

        except IntegrityError as exc:
            db.rollback()

            raise (
                OrthobiologicMaterialCodeConflictError(
                    "Orthobiologic material "
                    f"'{payload.code}' "
                    "already exists."
                )
            ) from exc

        AuditLogRepository.create(
            db,
            entity_type=(
                "orthobiologic_material"
            ),
            entity_id=material.id,
            event_type=(
                "orthobiologic_material_created"
            ),
            from_state=None,
            to_state="active",
            message=(
                "Orthobiologic material created."
            ),
            event_data={
                "code": material.code,
                "name": material.name,
                "category": material.category,
                "is_autologous": (
                    material.is_autologous
                ),
                "requires_lot_tracking": (
                    material.requires_lot_tracking
                ),
            },
            **actor_data(actor),
        )

        return material

    @staticmethod
    def get_material(
        db: Session,
        material_id: str,
    ) -> OrthobiologicMaterial:
        material = (
            OrthobiologicMaterialRepository
            .get_by_id(
                db,
                material_id,
            )
        )

        if material is None:
            raise (
                OrthobiologicMaterialNotFoundError(
                    "Orthobiologic material "
                    f"'{material_id}' "
                    "was not found."
                )
            )

        return material

    @staticmethod
    def list_materials(
        db: Session,
        *,
        active_only: bool = True,
        category: str | None = None,
    ) -> list[OrthobiologicMaterial]:
        normalized_category = None

        if category is not None:
            normalized_category = (
                category.strip().lower()
            )

        return (
            OrthobiologicMaterialRepository.list(
                db,
                active_only=active_only,
                category=normalized_category,
            )
        )

    @staticmethod
    def deactivate_material(
        db: Session,
        material_id: str,
        actor: User | None = None,
    ) -> OrthobiologicMaterial:
        material = (
            OrthobiologicMaterialService
            .get_material(
                db,
                material_id,
            )
        )

        if not material.is_active:
            return material

        updated_material = (
            OrthobiologicMaterialRepository
            .deactivate(
                db,
                material,
            )
        )

        AuditLogRepository.create(
            db,
            entity_type=(
                "orthobiologic_material"
            ),
            entity_id=updated_material.id,
            event_type=(
                "orthobiologic_material_deactivated"
            ),
            from_state="active",
            to_state="inactive",
            message=(
                "Orthobiologic material deactivated."
            ),
            event_data={
                "code": updated_material.code,
                "name": updated_material.name,
            },
            **actor_data(actor),
        )

        return updated_material
