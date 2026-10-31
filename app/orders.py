from fastapi import APIRouter, HTTPException

from app.config import settings
from app.database import get_connection
from app.email_service import send_order_receipt_email
from app.schemas import OrderHeadCreate, OrderHeadResponse, OrderDetailResponse
from app.whatsapp_service import (
    build_whatsapp_web_url,
    format_whatsapp_receipt_text,
    send_order_receipt_whatsapp,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("", response_model=OrderHeadResponse, status_code=201)
def create_order(payload: OrderHeadCreate) -> OrderHeadResponse:
    """
    Create a new order with one or more line items.

    - Inserts a row in `order_head` and returns its generated `id`.
    - Inserts each item in `order_details` linked to that order.
    - Sends receipt via email and/or WhatsApp if requested.
    - Returns the full order with notification delivery statuses and bill info.
    """
    if not payload.items:
        raise HTTPException(status_code=422, detail="Order must contain at least one item.")

    order_type = payload.order_type.lower()
    if order_type not in ("online", "offline", "phone"):
        raise HTTPException(status_code=422, detail="order_type must be 'online', 'offline', or 'phone'.")

    payment_status = payload.payment_status.lower()
    if payment_status not in ("success", "cancel", "failed", "pending", "cancelled"):
        raise HTTPException(
            status_code=422,
            detail="payment_status must be 'success', 'cancel', 'failed', or 'pending'.",
        )

    if payload.paid_status not in (0, 1):
        raise HTTPException(status_code=422, detail="paid_status must be 0 or 1.")

    with get_connection() as conn:
        # ── 1. Insert order header ─────────────────────────────────────────
        head_row = conn.execute(
            """
            INSERT INTO order_head (
                customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id, customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status, order_datetime
            """,
            (
                payload.customer_name.strip(),
                payload.phone.strip(),
                str(payload.email or "").strip().lower(),
                payload.address.strip(),
                order_type,
                payload.total_price,
                payload.payment_mode.strip(),
                payment_status,
                payload.paid_status,
            ),
        ).fetchone()

        if not head_row:
            raise HTTPException(status_code=500, detail="Failed to create order.")

        order_id = head_row["id"]

        # ── 2. Insert line items ───────────────────────────────────────────
        inserted_items: list[OrderDetailResponse] = []
        for item in payload.items:
            detail_row = conn.execute(
                """
                INSERT INTO order_details (
                    order_id, product_name, quantity, unit_price, total_price
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, order_id, product_name, quantity, unit_price, total_price
                """,
                (
                    order_id,
                    item.product_name.strip(),
                    item.quantity,
                    item.unit_price,
                    item.total_price,
                ),
            ).fetchone()

            if not detail_row:
                raise HTTPException(status_code=500, detail="Failed to insert order item.")

            inserted_items.append(OrderDetailResponse.model_validate(detail_row))

    # ── 3. Dispatch Notifications (Email & WhatsApp) ───────────────────────
    order_dict = {
        "id": head_row["id"],
        "customer_name": head_row["customer_name"],
        "phone": head_row["phone"],
        "email": head_row["email"],
        "address": head_row["address"],
        "order_type": head_row["order_type"],
        "total_price": head_row["total_price"],
        "payment_mode": head_row["payment_mode"],
        "payment_status": head_row["payment_status"],
        "paid_status": head_row["paid_status"],
        "order_datetime": head_row["order_datetime"],
        "items": [i.model_dump() for i in inserted_items],
    }

    email_sent = False
    if payload.send_email and order_dict.get("email"):
        try:
            email_sent = send_order_receipt_email(order_dict)
        except Exception:
            email_sent = False

    whatsapp_sent = False
    if payload.send_whatsapp and order_dict.get("phone"):
        try:
            whatsapp_sent = send_order_receipt_whatsapp(order_dict)
        except Exception:
            whatsapp_sent = False

    whatsapp_url = build_whatsapp_web_url(
        head_row["phone"],
        format_whatsapp_receipt_text(order_dict)
    )

    # ── 4. Build and return response ───────────────────────────────────────
    return OrderHeadResponse(
        id=head_row["id"],
        customer_name=head_row["customer_name"],
        phone=head_row["phone"],
        email=head_row["email"],
        address=head_row["address"],
        order_type=head_row["order_type"],
        total_price=head_row["total_price"],
        payment_mode=head_row["payment_mode"],
        payment_status=head_row["payment_status"],
        paid_status=head_row["paid_status"],
        order_datetime=head_row["order_datetime"],
        items=inserted_items,
        email_sent=email_sent,
        whatsapp_sent=whatsapp_sent,
        whatsapp_url=whatsapp_url,
        gst_number=getattr(settings, "gst_number", "27AABCM1234F1Z1"),
    )
