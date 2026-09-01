from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.orthobiologic_material import (
    OrthobiologicMaterial,
)


MATERIALS = [
    {
        "code": "ACS",
        "name": "Autologous Conditioned Serum",
        "category": "orthobiologic",
        "default_unit": "ml",
        "is_autologous": True,
        "requires_lot_tracking": False,
    },
    {
        "code": "PRP",
        "name": "Platelet-Rich Plasma",
        "category": "orthobiologic",
        "default_unit": "ml",
        "is_autologous": True,
        "requires_lot_tracking": False,
    },
    {
        "code": "PRGF",
        "name": "Plasma Rich in Growth Factors",
        "category": "orthobiologic",
        "default_unit": "ml",
        "is_autologous": True,
        "requires_lot_tracking": False,
    },
    {
        "code": "PL",
        "name": "Platelet Lysate",
        "category": "orthobiologic",
        "default_unit": "ml",
        "is_autologous": True,
        "requires_lot_tracking": False,
    },
    {
        "code": "EXOSOME",
        "name": "Exosome",
        "category": "biologic",
        "default_unit": "vial",
        "is_autologous": False,
        "requires_lot_tracking": True,
    },
    {
        "code": "SVF",
        "name": "Stromal Vascular Fraction",
        "category": "orthobiologic",
        "default_unit": "ml",
        "is_autologous": True,
        "requires_lot_tracking": False,
    },
    {
        "code": "BMAC",
        "name": "Bone Marrow Aspirate Concentrate",
        "category": "orthobiologic",
        "default_unit": "ml",
        "is_autologous": True,
        "requires_lot_tracking": False,
    },
    {
        "code": "HA",
        "name": "Hyaluronic Acid",
        "category": "biologic",
        "default_unit": "ml",
        "is_autologous": False,
        "requires_lot_tracking": True,
    },
]


def main() -> None:
    db = SessionLocal()

    try:
        for material_data in MATERIALS:
            existing = db.scalar(
                select(
                    OrthobiologicMaterial
                ).where(
                    OrthobiologicMaterial.code
                    == material_data["code"]
                )
            )

            if existing is not None:
                continue

            db.add(
                OrthobiologicMaterial(
                    **material_data
                )
            )

        db.commit()

    finally:
        db.close()


if __name__ == "__main__":
    main()