from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_connection
from app.schemas import (
    AddressCreate,
    AddressResponse,
    AddressUpdate,
    UserResponse,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/addresses", tags=["addresses"])


def _format_address(row) -> AddressResponse:
    return AddressResponse(
        id=row["id"],
        user_id=row["user_id"],
        label=row["label"],
        full_name=row["full_name"],
        phone=row["phone"],
        address_line1=row["address_line1"],
        address_line2=row["address_line2"],
        city=row["city"],
        state=row["state"],
        pincode=row["pincode"],
        is_default=bool(row["is_default"]),
        created_at=row["created_at"],
    )


@router.get("", response_model=list[AddressResponse])
def get_addresses(user: UserResponse = Depends(get_current_user)) -> list[AddressResponse]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, label, full_name, phone,
                   address_line1, address_line2, city, state, pincode,
                   is_default, created_at
            FROM user_addresses
            WHERE user_id = %s
            ORDER BY is_default DESC, created_at DESC
            """,
            (user.id,),
        ).fetchall()
        return [_format_address(r) for r in rows]


@router.post("", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
def create_address(
    payload: AddressCreate,
    user: UserResponse = Depends(get_current_user),
) -> AddressResponse:
    with get_connection() as conn:
        is_default = 1 if payload.is_default else 0

        # If user has no existing addresses, make this one default automatically
        existing_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_addresses WHERE user_id = %s",
            (user.id,),
        ).fetchone()
        if existing_count and existing_count["cnt"] == 0:
            is_default = 1

        if is_default == 1:
            conn.execute(
                "UPDATE user_addresses SET is_default = 0 WHERE user_id = %s",
                (user.id,),
            )

        row = conn.execute(
            """
            INSERT INTO user_addresses (
                user_id, label, full_name, phone,
                address_line1, address_line2, city, state, pincode, is_default
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, user_id, label, full_name, phone,
                      address_line1, address_line2, city, state, pincode,
                      is_default, created_at
            """,
            (
                user.id,
                payload.label.strip(),
                payload.full_name.strip(),
                payload.phone.strip(),
                payload.address_line1.strip(),
                payload.address_line2.strip() if payload.address_line2 else None,
                payload.city.strip(),
                payload.state.strip(),
                payload.pincode.strip(),
                is_default,
            ),
        ).fetchone()

        if not row:
            # Fallback for SQLite without RETURNING if needed
            last_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            row = conn.execute(
                "SELECT * FROM user_addresses WHERE id = %s", (last_id,)
            ).fetchone()

        return _format_address(row)


@router.patch("/{address_id}", response_model=AddressResponse)
def update_address(
    address_id: int,
    payload: AddressUpdate,
    user: UserResponse = Depends(get_current_user),
) -> AddressResponse:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM user_addresses WHERE id = %s AND user_id = %s",
            (address_id, user.id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Address not found.")

        updates = []
        params = []

        if payload.label is not None:
            updates.append("label = %s")
            params.append(payload.label.strip())
        if payload.full_name is not None:
            updates.append("full_name = %s")
            params.append(payload.full_name.strip())
        if payload.phone is not None:
            updates.append("phone = %s")
            params.append(payload.phone.strip())
        if payload.address_line1 is not None:
            updates.append("address_line1 = %s")
            params.append(payload.address_line1.strip())
        if payload.address_line2 is not None:
            updates.append("address_line2 = %s")
            params.append(payload.address_line2.strip())
        if payload.city is not None:
            updates.append("city = %s")
            params.append(payload.city.strip())
        if payload.state is not None:
            updates.append("state = %s")
            params.append(payload.state.strip())
        if payload.pincode is not None:
            updates.append("pincode = %s")
            params.append(payload.pincode.strip())
        if payload.is_default is not None:
            is_def = 1 if payload.is_default else 0
            if is_def == 1:
                conn.execute(
                    "UPDATE user_addresses SET is_default = 0 WHERE user_id = %s",
                    (user.id,),
                )
            updates.append("is_default = %s")
            params.append(is_def)

        if updates:
            params.append(address_id)
            params.append(user.id)
            conn.execute(
                f"UPDATE user_addresses SET {', '.join(updates)} WHERE id = %s AND user_id = %s",
                tuple(params),
            )

        updated = conn.execute(
            "SELECT * FROM user_addresses WHERE id = %s AND user_id = %s",
            (address_id, user.id),
        ).fetchone()
        return _format_address(updated)


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(
    address_id: int,
    user: UserResponse = Depends(get_current_user),
):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM user_addresses WHERE id = %s AND user_id = %s",
            (address_id, user.id),
        )


@router.patch("/{address_id}/default", response_model=AddressResponse)
def set_default_address(
    address_id: int,
    user: UserResponse = Depends(get_current_user),
) -> AddressResponse:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM user_addresses WHERE id = %s AND user_id = %s",
            (address_id, user.id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Address not found.")

        conn.execute(
            "UPDATE user_addresses SET is_default = 0 WHERE user_id = %s",
            (user.id,),
        )
        conn.execute(
            "UPDATE user_addresses SET is_default = 1 WHERE id = %s AND user_id = %s",
            (address_id, user.id),
        )

        updated = conn.execute(
            "SELECT * FROM user_addresses WHERE id = %s", (address_id,)
        ).fetchone()
        return _format_address(updated)
