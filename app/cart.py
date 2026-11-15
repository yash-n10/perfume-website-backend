from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_connection
from app.schemas import (
    CartItemAdd,
    CartItemResponse,
    CartItemUpdate,
    CartResponse,
    UserResponse,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/cart", tags=["cart"])


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
        # Validate product
        prod = conn.execute(
            "SELECT id FROM products WHERE id = %s",
            (payload.product_id,),
        ).fetchone()
        if not prod:
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
