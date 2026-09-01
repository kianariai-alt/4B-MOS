from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.orthobiologic_material import (
    OrthobiologicMaterial,
)
from backend.app.schemas.orthobiologic_material import (
    OrthobiologicMaterialCreate,
)


class OrthobiologicMaterialRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        material_id: str,
    ) -> OrthobiologicMaterial | None:
        return db.get(
            OrthobiologicMaterial,
            material_id,
        )

    @staticmethod
    def get_by_code(
        db: Session,
        code: str,
    ) -> OrthobiologicMaterial | None:
        statement = select(
            OrthobiologicMaterial
        ).where(
            OrthobiologicMaterial.code == code
        )

        return db.scalar(statement)

    @staticmethod
    def list(
        db: Session,
        *,
        active_only: bool = False,
        category: str | None = None,
    ) -> list[OrthobiologicMaterial]:
        statement = select(
            OrthobiologicMaterial
        ).order_by(
            OrthobiologicMaterial.code.asc()
        )

        if active_only:
            statement = statement.where(
                OrthobiologicMaterial.is_active
                .is_(True)
            )

        if category is not None:
            statement = statement.where(
                OrthobiologicMaterial.category
                == category
            )

        return list(
            db.scalars(statement).all()
        )

    @staticmethod
    def create(
        db: Session,
        payload: OrthobiologicMaterialCreate,
    ) -> OrthobiologicMaterial:
        material = OrthobiologicMaterial(
            **payload.model_dump(),
        )

        db.add(material)
        db.commit()
        db.refresh(material)

        return material

    @staticmethod
    def deactivate(
        db: Session,
        material: OrthobiologicMaterial,
    ) -> OrthobiologicMaterial:
        material.is_active = False

        db.add(material)
        db.commit()
        db.refresh(material)

        return material
