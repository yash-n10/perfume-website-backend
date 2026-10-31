from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.database import get_connection
from app.email_service import send_order_receipt_email
from app.schemas import (
    OrderDetailResponse,
    OrderHeadCreate,
    OrderHeadResponse,
    OrderStatusUpdateRequest,
)
from app.security import get_current_admin
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
        format_whatsapp_receipt_text(order_dict),
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


@router.get("", response_model=list[OrderHeadResponse])
def list_orders(
    status: Optional[str] = Query(default=None, description="Filter by payment status"),
    order_type: Optional[str] = Query(default=None, description="Filter by order type"),
    search: Optional[str] = Query(default=None, description="Search by customer name, phone, or email"),
    admin: dict = Depends(get_current_admin),
) -> list[OrderHeadResponse]:
    """
    Admin: Fetch order list with items, totals, and delivery info.
    Supports filtering and search.
    """
    with get_connection() as conn:
        conditions = []
        params = []

        if status:
            conditions.append("payment_status = %s")
            params.append(status.lower())

        if order_type:
            conditions.append("order_type = %s")
            params.append(order_type.lower())

        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            conditions.append(
                "(LOWER(customer_name) LIKE %s OR LOWER(phone) LIKE %s OR LOWER(email) LIKE %s)"
            )
            params.extend([term, term, term])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT id, customer_name, phone, email, address,
                   order_type, total_price, payment_mode,
                   payment_status, paid_status, order_datetime
            FROM order_head
            {where_clause}
            ORDER BY id DESC
        """

        head_rows = conn.execute(query, tuple(params)).fetchall()
        orders: list[OrderHeadResponse] = []

        for h in head_rows:
            order_id = h["id"]
            detail_rows = conn.execute(
                """
                SELECT id, order_id, product_name, quantity, unit_price, total_price
                FROM order_details
                WHERE order_id = %s
                ORDER BY id ASC
                """,
                (order_id,),
            ).fetchall()

            items = [OrderDetailResponse.model_validate(d) for d in detail_rows]
            order_dict = {
                "id": h["id"],
                "customer_name": h["customer_name"],
                "phone": h["phone"],
                "email": h["email"],
                "address": h["address"],
                "order_type": h["order_type"],
                "total_price": h["total_price"],
                "payment_mode": h["payment_mode"],
                "payment_status": h["payment_status"],
                "paid_status": h["paid_status"],
                "order_datetime": h["order_datetime"],
                "items": items,
            }

            whatsapp_url = build_whatsapp_web_url(
                h["phone"],
                format_whatsapp_receipt_text(order_dict),
            )

            orders.append(
                OrderHeadResponse(
                    id=h["id"],
                    customer_name=h["customer_name"],
                    phone=h["phone"],
                    email=h["email"],
                    address=h["address"],
                    order_type=h["order_type"],
                    total_price=h["total_price"],
                    payment_mode=h["payment_mode"],
                    payment_status=h["payment_status"],
                    paid_status=h["paid_status"],
                    order_datetime=h["order_datetime"],
                    items=items,
                    email_sent=False,
                    whatsapp_sent=False,
                    whatsapp_url=whatsapp_url,
                    gst_number=getattr(settings, "gst_number", "27AABCM1234F1Z1"),
                )
            )

        return orders


@router.get("/{order_id}", response_model=OrderHeadResponse)
def get_order(
    order_id: int,
    admin: dict = Depends(get_current_admin),
) -> OrderHeadResponse:
    """Admin: Fetch single order by ID."""
    with get_connection() as conn:
        h = conn.execute(
            """
            SELECT id, customer_name, phone, email, address,
                   order_type, total_price, payment_mode,
                   payment_status, paid_status, order_datetime
            FROM order_head
            WHERE id = %s
            """,
            (order_id,),
        ).fetchone()

        if not h:
            raise HTTPException(status_code=404, detail="Order not found.")

        detail_rows = conn.execute(
            """
            SELECT id, order_id, product_name, quantity, unit_price, total_price
            FROM order_details
            WHERE order_id = %s
            ORDER BY id ASC
            """,
            (order_id,),
        ).fetchall()

        items = [OrderDetailResponse.model_validate(d) for d in detail_rows]
        order_dict = {
            "id": h["id"],
            "customer_name": h["customer_name"],
            "phone": h["phone"],
            "email": h["email"],
            "address": h["address"],
            "order_type": h["order_type"],
            "total_price": h["total_price"],
            "payment_mode": h["payment_mode"],
            "payment_status": h["payment_status"],
            "paid_status": h["paid_status"],
            "order_datetime": h["order_datetime"],
            "items": items,
        }

        whatsapp_url = build_whatsapp_web_url(
            h["phone"],
            format_whatsapp_receipt_text(order_dict),
        )

        return OrderHeadResponse(
            id=h["id"],
            customer_name=h["customer_name"],
            phone=h["phone"],
            email=h["email"],
            address=h["address"],
            order_type=h["order_type"],
            total_price=h["total_price"],
            payment_mode=h["payment_mode"],
            payment_status=h["payment_status"],
            paid_status=h["paid_status"],
            order_datetime=h["order_datetime"],
            items=items,
            whatsapp_url=whatsapp_url,
            gst_number=getattr(settings, "gst_number", "27AABCM1234F1Z1"),
        )


@router.patch("/{order_id}/status", response_model=OrderHeadResponse)
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdateRequest,
    admin: dict = Depends(get_current_admin),
) -> OrderHeadResponse:
    """Admin: Update order payment or paid status."""
    updates = []
    params = []

    if payload.payment_status is not None:
        st = payload.payment_status.lower()
        if st not in ("success", "pending", "failed", "cancelled", "cancel"):
            raise HTTPException(status_code=422, detail="Invalid payment status.")
        updates.append("payment_status = %s")
        params.append(st)

    if payload.paid_status is not None:
        if payload.paid_status not in (0, 1):
            raise HTTPException(status_code=422, detail="paid_status must be 0 or 1.")
        updates.append("paid_status = %s")
        params.append(payload.paid_status)

    if not updates:
        raise HTTPException(status_code=400, detail="No status fields provided to update.")

    params.append(order_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE order_head SET {', '.join(updates)} WHERE id = %s",
            tuple(params),
        )

    return get_order(order_id, admin)
