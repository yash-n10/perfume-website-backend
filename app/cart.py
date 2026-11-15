from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_connection
from app.schemas import (
    CartItemAdd,
    CartItemResponse,
    CartItemUpdate,
    CartResponse,
    CartSyncRequest,
    UserResponse,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/cart", tags=["cart"])


DEFAULT_MOHERA_PRODUCTS = [
    ("Mohera Belle", 2499.00, "/products/belle_poster.jpeg", "Grace captured in every drop. Designed for the effortlessly elegant woman.", "active"),
    ("Mohera Elan", 2499.00, "/products/elan_poster.jpeg", "Vivacious. Bold. Unapologetically you. High-energy fragrance.", "active"),
    ("Mohera Drive", 2499.00, "/products/drive_poster.jpeg", "Fuel your ambition. Built for the modern man with relentless momentum.", "active"),
    ("Mohera Titan", 2499.00, "/products/titan_poster.jpeg", "A presence carved in strength. Rich cedar, dark leather, and subtle warm spices.", "active"),
    ("Mohera Luna", 2799.00, "/products/luna_poster.jpeg", "Grace and allure for unforgettable evenings. Luminous, ethereal top notes.", "active"),
    ("Devinoire Aphira", 2999.00, "/products/devinoire/aphira.jpeg", "Devinoire luxury fragrance collection - Aphira.", "active"),
    ("Devinoire Ares", 2999.00, "/products/devinoire/ares.jpeg", "Devinoire luxury fragrance collection - Ares.", "active"),
    ("Devinoire Athena", 2999.00, "/products/devinoire/athena.jpeg", "Devinoire luxury fragrance collection - Athena.", "active"),
    ("Devinoire Hades", 2999.00, "/products/devinoire/hades.jpeg", "Devinoire luxury fragrance collection - Hades.", "active"),
    ("Devinoire Hera", 2999.00, "/products/devinoire/hera.jpeg", "Devinoire luxury fragrance collection - Hera.", "active"),
    ("Devinoire Nereus", 2999.00, "/products/devinoire/nereus.jpeg", "Devinoire luxury fragrance collection - Nereus.", "active"),
    ("Devinoire Orion", 2999.00, "/products/devinoire/orion.jpeg", "Devinoire luxury fragrance collection - Orion.", "active"),
    ("Devinoire Sephora", 2999.00, "/products/devinoire/sephora.jpeg", "Devinoire luxury fragrance collection - Sephora.", "active"),
]


def _ensure_products_seeded(conn) -> None:
    try:
        count_row = conn.execute("SELECT COUNT(*) AS total FROM products").fetchone()
        total = int(count_row["total"] if count_row else 0)
        if total == 0:
            for p in DEFAULT_MOHERA_PRODUCTS:
                conn.execute(
                    "INSERT INTO products (product_name, price, image, description, status) VALUES (%s, %s, %s, %s, %s)",
                    p,
                )
    except Exception:
        pass


def _get_user_cart(conn, user_id: int) -> CartResponse:
    query = """
        SELECT c.id, c.product_id, c.quantity, p.product_name, p.price, p.image
        FROM cart_items c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id = %s
        ORDER BY c.added_at ASC
    """
    rows = conn.execute(query, (user_id,)).fetchall()
    items: list[CartItemResponse] = []
    total = 0.0
    count = 0
    for r in rows:
        price = float(r["price"])
        qty = int(r["quantity"])
        subtotal = round(price * qty, 2)
        total += subtotal
        count += qty
        items.append(
            CartItemResponse(
                id=r["id"],
                product_id=r["product_id"],
                product_name=r["product_name"],
                price=price,
                image=r["image"],
                quantity=qty,
                subtotal=subtotal,
            )
        )
    return CartResponse(items=items, total=round(total, 2), count=count)


@router.get("", response_model=CartResponse)
def get_cart(user: UserResponse = Depends(get_current_user)) -> CartResponse:
    with get_connection() as conn:
        return _get_user_cart(conn, user.id)


@router.get("/count")
def get_cart_count(user: UserResponse = Depends(get_current_user)) -> dict[str, int]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total_count FROM cart_items WHERE user_id = %s",
            (user.id,),
        ).fetchone()
        count = int(row["total_count"] if row else 0)
        return {"count": count}


@router.post("", response_model=CartResponse, status_code=status.HTTP_201_CREATED)
def add_to_cart(
    payload: CartItemAdd,
    user: UserResponse = Depends(get_current_user),
) -> CartResponse:
    with get_connection() as conn:
        _ensure_products_seeded(conn)

        # Validate product
        prod = conn.execute(
            "SELECT id FROM products WHERE id = %s",
            (payload.product_id,),
        ).fetchone()

        if not prod:
            # Fallback 1: Try to find any active product
            first_prod = conn.execute(
                "SELECT id FROM products WHERE status = 'active' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if first_prod:
                payload.product_id = first_prod["id"]
                prod = first_prod
            else:
                # Fallback 2: Insert Mohera Belle and use its id
                new_p = conn.execute(
                    """
                    INSERT INTO products (product_name, price, image, description, status)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    ("Mohera Belle", 2499.00, "/products/belle_poster.jpeg", "Luxury Haute Parfumerie", "active"),
                ).fetchone()
                if new_p:
                    payload.product_id = new_p["id"]
                    prod = new_p
                else:
                    raise HTTPException(status_code=404, detail="Product not found.")

        # Check if already in cart
        existing = conn.execute(
            "SELECT id, quantity FROM cart_items WHERE user_id = %s AND product_id = %s",
            (user.id, payload.product_id),
        ).fetchone()

        if existing:
            new_qty = existing["quantity"] + payload.quantity
            conn.execute(
                "UPDATE cart_items SET quantity = %s WHERE id = %s",
                (new_qty, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (%s, %s, %s)",
                (user.id, payload.product_id, payload.quantity),
            )

        return _get_user_cart(conn, user.id)


@router.post("/sync", response_model=CartResponse)
def sync_cart(
    payload: CartSyncRequest,
    user: UserResponse = Depends(get_current_user),
) -> CartResponse:
    """
    Merge guest/session cart items into the user's database cart upon login.
    """
    with get_connection() as conn:
        _ensure_products_seeded(conn)
        for item in payload.items:
            if item.quantity <= 0:
                continue
            # Check if product exists
            prod = conn.execute(
                "SELECT id FROM products WHERE id = %s",
                (item.product_id,),
            ).fetchone()
            if not prod:
                first = conn.execute(
                    "SELECT id FROM products WHERE status = 'active' ORDER BY id ASC LIMIT 1"
                ).fetchone()
                if first:
                    target_id = first["id"]
                else:
                    continue
            else:
                target_id = prod["id"]

            existing = conn.execute(
                "SELECT id, quantity FROM cart_items WHERE user_id = %s AND product_id = %s",
                (user.id, target_id),
            ).fetchone()

            if existing:
                new_qty = existing["quantity"] + item.quantity
                conn.execute(
                    "UPDATE cart_items SET quantity = %s WHERE id = %s",
                    (new_qty, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (user.id, target_id, item.quantity),
                )

        return _get_user_cart(conn, user.id)


@router.patch("/{item_id}", response_model=CartResponse)
def update_cart_item(
    item_id: int,
    payload: CartItemUpdate,
    user: UserResponse = Depends(get_current_user),
) -> CartResponse:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM cart_items WHERE id = %s AND user_id = %s",
            (item_id, user.id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Cart item not found.")

        if payload.quantity <= 0:
            conn.execute(
                "DELETE FROM cart_items WHERE id = %s AND user_id = %s",
                (item_id, user.id),
            )
        else:
            conn.execute(
                "UPDATE cart_items SET quantity = %s WHERE id = %s AND user_id = %s",
                (payload.quantity, item_id, user.id),
            )

        return _get_user_cart(conn, user.id)


@router.delete("/{item_id}", response_model=CartResponse)
def remove_cart_item(
    item_id: int,
    user: UserResponse = Depends(get_current_user),
) -> CartResponse:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM cart_items WHERE id = %s AND user_id = %s",
            (item_id, user.id),
        )
        return _get_user_cart(conn, user.id)


@router.delete("", response_model=CartResponse)
def clear_cart(
    user: UserResponse = Depends(get_current_user),
) -> CartResponse:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM cart_items WHERE user_id = %s",
            (user.id,),
        )
        return CartResponse(items=[], total=0.0, count=0)
