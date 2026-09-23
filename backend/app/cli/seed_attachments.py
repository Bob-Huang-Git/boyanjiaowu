# ruff: noqa: E501, E702
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import (
    DocumentCategory,
    DocumentCategoryAllowedType,
    StudentDocumentRequirement,
)

CATEGORIES = [
    ("ID_CARD_FRONT", "身份证正面", "HIGHLY_SENSITIVE", True),
    ("ID_CARD_BACK", "身份证反面", "HIGHLY_SENSITIVE", True),
    ("PROFILE_PHOTO", "学员照片", "SENSITIVE", False),
    ("REGISTRATION_FORM", "报名表", "SENSITIVE", True),
    ("EDUCATION_CERTIFICATE", "学历证明", "SENSITIVE", True),
    ("TRAINING_AGREEMENT", "培训协议", "HIGHLY_SENSITIVE", True),
    ("HOUSEHOLD_PROOF", "户籍证明", "HIGHLY_SENSITIVE", True),
    ("OTHER", "其他材料", "NORMAL", False),
]
TYPES = [
    ("pdf", "application/pdf", False),
    ("jpg", "image/jpeg", True),
    ("jpeg", "image/jpeg", True),
    ("png", "image/png", True),
    ("webp", "image/webp", True),
]


def main() -> None:
    with Session(get_engine()) as db:
        for order, (code, name, sensitivity, required) in enumerate(CATEGORIES, 1):
            category = db.scalar(
                select(DocumentCategory).where(DocumentCategory.category_code == code)
            )
            if category is None:
                category = DocumentCategory(
                    category_code=code,
                    category_name=name,
                    sensitivity_level=sensitivity,
                    max_size_bytes=20 * 1024 * 1024,
                    requires_review=True,
                    display_order=order,
                )
                db.add(category)
                db.flush()
            for extension, mime_type, inline_preview in TYPES:
                if (
                    db.scalar(
                        select(DocumentCategoryAllowedType).where(
                            DocumentCategoryAllowedType.category_id == category.id,
                            DocumentCategoryAllowedType.extension == extension,
                        )
                    )
                    is None
                ):
                    db.add(
                        DocumentCategoryAllowedType(
                            category_id=category.id,
                            extension=extension,
                            mime_type=mime_type,
                            detected_content_type=mime_type,
                            inline_preview=inline_preview,
                        )
                    )
            if (
                required
                and db.scalar(
                    select(StudentDocumentRequirement).where(
                        StudentDocumentRequirement.requirement_code == f"BASE_{code}"
                    )
                )
                is None
            ):
                db.add(
                    StudentDocumentRequirement(
                        requirement_code=f"BASE_{code}",
                        requirement_name=name,
                        category_id=category.id,
                        display_order=order,
                    )
                )
        db.commit()
    print("Attachment categories seeded")


if __name__ == "__main__":
    main()
