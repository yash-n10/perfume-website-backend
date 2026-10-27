from fastapi import APIRouter

from app.database import get_connection
from app.schemas import EnquiryCreate, EnquiryResponse


router = APIRouter(prefix="/api/enquiries", tags=["enquiries"])


@router.post("", response_model=EnquiryResponse, status_code=201)
def create_enquiry(payload: EnquiryCreate) -> EnquiryResponse:
    with get_connection() as connection:
        enquiry = connection.execute(
            """
            INSERT INTO enquiries (name, email, phone, enquiry)
            VALUES (%s, %s, %s, %s)
            RETURNING id, status, created_at
            """,
            (
                payload.name.strip(),
                str(payload.email).strip().lower(),
                payload.phone.strip(),
                payload.enquiry.strip(),
            ),
        ).fetchone()

    return EnquiryResponse.model_validate(enquiry)