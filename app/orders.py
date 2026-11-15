from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.database import get_connection
from app.email_service import send_order_receipt_email
from app.schemas import (
    CheckoutRequest,
    GuestCheckoutRequest,
    OrderDetailResponse,
    OrderHeadCreate,
    OrderHeadResponse,
    OrderStatusUpdateRequest,
    UserResponse,
)
from app.security import get_current_admin, get_current_user
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
                user_id, customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id, user_id, customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status, order_datetime
            """,
            (
                payload.user_id,
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
                    order_id, product_id, product_name, quantity, unit_price, total_price
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, order_id, product_id, product_name, quantity, unit_price, total_price
                """,
                (
                    order_id,
                    getattr(item, "product_id", None),
                    item.product_name.strip(),
                    item.quantity,
                    item.unit_price,
                    item.total_price,
                ),
            ).fetchone()

            if not detail_row:
                raise HTTPException(status_code=500, detail="Failed to insert order item.")

            inserted_items.append(OrderDetailResponse.model_validate(detail_row))

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
        user_id=head_row.get("user_id"),
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


@router.post("/checkout", response_model=OrderHeadResponse, status_code=201)
def checkout_cart(
    payload: CheckoutRequest,
    user: UserResponse = Depends(get_current_user),
) -> OrderHeadResponse:
    """
    Authenticated Checkout:
    - Verifies user's cart
    - Resolves shipping address (selected from address book or provided inline)
    - Creates order in order_head with user_id
    - Inserts line items in order_details
    - Clears user's cart
    - Sends notifications
    """
    with get_connection() as conn:
        # 1. Fetch cart items
        cart_rows = conn.execute(
            """
            SELECT c.id, c.product_id, c.quantity, p.product_name, p.price
            FROM cart_items c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
            ORDER BY c.added_at ASC
            """,
            (user.id,),
        ).fetchall()

        if not cart_rows:
            raise HTTPException(status_code=400, detail="Your cart is empty. Add products before checkout.")

        # 2. Resolve address
        customer_name = user.name
        phone = user.phone
        email = str(user.email)
        shipping_address = ""

        if payload.address_id:
            addr = conn.execute(
                "SELECT * FROM user_addresses WHERE id = %s AND user_id = %s",
                (payload.address_id, user.id),
            ).fetchone()
            if not addr:
                raise HTTPException(status_code=404, detail="Selected delivery address not found.")
            customer_name = addr["full_name"]
            phone = addr["phone"]
            parts = [addr["address_line1"]]
            if addr.get("address_line2"):
                parts.append(addr["address_line2"])
            parts.append(f"{addr['city']}, {addr['state']} - {addr['pincode']}")
            shipping_address = f"[{addr['label']}] " + ", ".join(parts)
        elif payload.address:
            a = payload.address
            customer_name = a.full_name
            phone = a.phone
            parts = [a.address_line1]
            if a.address_line2:
                parts.append(a.address_line2)
            parts.append(f"{a.city}, {a.state} - {a.pincode}")
            shipping_address = f"[{a.label}] " + ", ".join(parts)

            # Also persist in user_addresses
            conn.execute(
                """
                INSERT INTO user_addresses (
                    user_id, label, full_name, phone,
                    address_line1, address_line2, city, state, pincode, is_default
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user.id,
                    a.label.strip(),
                    a.full_name.strip(),
                    a.phone.strip(),
                    a.address_line1.strip(),
                    a.address_line2.strip() if a.address_line2 else None,
                    a.city.strip(),
                    a.state.strip(),
                    a.pincode.strip(),
                    1 if a.is_default else 0,
                ),
            )
        else:
            raise HTTPException(status_code=400, detail="Please select or provide a shipping address.")

        # 3. Calculate total
        total_price = sum(round(float(item["price"]) * int(item["quantity"]), 2) for item in cart_rows)
        total_price = round(total_price, 2)

        # 4. Insert order_head
        payment_mode = payload.payment_mode or "Cash on Delivery"
        head_row = conn.execute(
            """
            INSERT INTO order_head (
                user_id, customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id, user_id, customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status, order_datetime
            """,
            (
                user.id,
                customer_name.strip(),
                phone.strip(),
                email.strip().lower(),
                shipping_address.strip(),
                "online",
                total_price,
                payment_mode.strip(),
                "pending",
                0,
            ),
        ).fetchone()

        if not head_row:
            raise HTTPException(status_code=500, detail="Failed to place order.")

        order_id = head_row["id"]

        # 5. Insert line items
        inserted_items: list[OrderDetailResponse] = []
        for c in cart_rows:
            unit_price = float(c["price"])
            quantity = int(c["quantity"])
            item_total = round(unit_price * quantity, 2)
            d_row = conn.execute(
                """
                INSERT INTO order_details (
                    order_id, product_id, product_name, quantity, unit_price, total_price
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, order_id, product_id, product_name, quantity, unit_price, total_price
                """,
                (
                    order_id,
                    c["product_id"],
                    c["product_name"].strip(),
                    quantity,
                    unit_price,
                    item_total,
                ),
            ).fetchone()
            inserted_items.append(OrderDetailResponse.model_validate(d_row))

        # 6. Clear user cart
        conn.execute("DELETE FROM cart_items WHERE user_id = %s", (user.id,))

    # 7. Notifications
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
    if order_dict.get("email"):
        try:
            email_sent = send_order_receipt_email(order_dict)
        except Exception:
            email_sent = False

    whatsapp_sent = False
    if order_dict.get("phone"):
        try:
            whatsapp_sent = send_order_receipt_whatsapp(order_dict)
        except Exception:
            whatsapp_sent = False

    whatsapp_url = build_whatsapp_web_url(
        head_row["phone"],
        format_whatsapp_receipt_text(order_dict),
    )

    return OrderHeadResponse(
        id=head_row["id"],
        user_id=head_row.get("user_id"),
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


@router.post("/guest-checkout", response_model=OrderHeadResponse, status_code=201)
def guest_checkout(payload: GuestCheckoutRequest) -> OrderHeadResponse:
    """
    Guest Checkout without login:
    - Creates order in order_head with user_id = None
    - Inserts line items in order_details
    - Sends receipt via email and/or WhatsApp
    - Returns OrderHeadResponse with id and invoice info
    """
    if not payload.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item.")

    parts = [payload.address_line1.strip()]
    if payload.address_line2:
        parts.append(payload.address_line2.strip())
    parts.append(f"{payload.city.strip()}, {payload.state.strip()} - {payload.pincode.strip()}")
    shipping_address = ", ".join(parts)

    total_price = sum(item.total_price for item in payload.items)
    total_price = round(total_price, 2)

    payment_mode = payload.payment_mode or "Cash on Delivery"

    with get_connection() as conn:
        head_row = conn.execute(
            """
            INSERT INTO order_head (
                user_id, customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status
            )
            VALUES (NULL, %s, %s, %s, %s, 'online', %s, %s, 'pending', 0)
            RETURNING
                id, user_id, customer_name, phone, email, address,
                order_type, total_price, payment_mode,
                payment_status, paid_status, order_datetime
            """,
            (
                payload.customer_name.strip(),
                payload.phone.strip(),
                payload.email.strip().lower() if payload.email else "",
                shipping_address.strip(),
                total_price,
                payment_mode.strip(),
            ),
        ).fetchone()

        if not head_row:
            raise HTTPException(status_code=500, detail="Failed to place order.")

        order_id = head_row["id"]

        inserted_items: list[OrderDetailResponse] = []
        for item in payload.items:
            detail_row = conn.execute(
                """
                INSERT INTO order_details (
                    order_id, product_id, product_name, quantity, unit_price, total_price
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, order_id, product_id, product_name, quantity, unit_price, total_price
                """,
                (
                    order_id,
                    item.product_id,
                    item.product_name.strip(),
                    item.quantity,
                    item.unit_price,
                    item.total_price,
                ),
            ).fetchone()
            inserted_items.append(OrderDetailResponse.model_validate(detail_row))

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
    if order_dict.get("email"):
        try:
            email_sent = send_order_receipt_email(order_dict)
        except Exception:
            email_sent = False

    whatsapp_sent = False
    if order_dict.get("phone"):
        try:
            whatsapp_sent = send_order_receipt_whatsapp(order_dict)
        except Exception:
            whatsapp_sent = False

    whatsapp_url = build_whatsapp_web_url(
        head_row["phone"],
        format_whatsapp_receipt_text(order_dict),
    )

    return OrderHeadResponse(
        id=head_row["id"],
        user_id=None,
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


@router.get("/my-orders", response_model=list[OrderHeadResponse])
def get_my_orders(
    user: UserResponse = Depends(get_current_user),
) -> list[OrderHeadResponse]:
    """
    Authenticated: Fetch all past orders for current logged-in user.
    """
    with get_connection() as conn:
        head_rows = conn.execute(
            """
            SELECT id, user_id, customer_name, phone, email, address,
                   order_type, total_price, payment_mode,
                   payment_status, paid_status, order_datetime
            FROM order_head
            WHERE user_id = %s OR lower(email) = %s
            ORDER BY id DESC
            """,
            (user.id, str(user.email).lower()),
        ).fetchall()

        orders: list[OrderHeadResponse] = []
        for h in head_rows:
            detail_rows = conn.execute(
                """
                SELECT id, order_id, product_id, product_name, quantity, unit_price, total_price
                FROM order_details
                WHERE order_id = %s
                ORDER BY id ASC
                """,
                (h["id"],),
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
                    user_id=h.get("user_id"),
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


@router.get("/my-orders/{order_id}", response_model=OrderHeadResponse)
def get_my_order_detail(
    order_id: int,
    user: UserResponse = Depends(get_current_user),
) -> OrderHeadResponse:
    """
    Authenticated: Fetch a single past order by ID for current logged-in user.
    """
    with get_connection() as conn:
        h = conn.execute(
            """
            SELECT id, user_id, customer_name, phone, email, address,
                   order_type, total_price, payment_mode,
                   payment_status, paid_status, order_datetime
            FROM order_head
            WHERE id = %s AND (user_id = %s OR lower(email) = %s)
            """,
            (order_id, user.id, str(user.email).lower()),
        ).fetchone()

        if not h:
            raise HTTPException(status_code=404, detail="Order not found.")

        detail_rows = conn.execute(
            """
            SELECT id, order_id, product_id, product_name, quantity, unit_price, total_price
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
            user_id=h.get("user_id"),
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
