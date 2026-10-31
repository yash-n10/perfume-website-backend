from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_connection
from app.schemas import ProductCreate, ProductResponse
from app.security import get_current_admin

router = APIRouter(prefix="/api/products", tags=["products"])


@router.post("", response_model=ProductResponse, status_code=201)
def create_product(
    payload: ProductCreate,
    admin: dict = Depends(get_current_admin),
) -> ProductResponse:
    """
    Admin: Add a new product to the catalogue.
    Requires admin Bearer token.
    """
    status = payload.status.lower()
    if status not in ("active", "inactive"):
        raise HTTPException(status_code=422, detail="status must be 'active' or 'inactive'.")

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO products (product_name, price, image, description, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, product_name, price, image, description, status, add_time
            """,
            (
                payload.product_name.strip(),
                payload.price,
                payload.image.strip() if payload.image else None,
                payload.description.strip() if payload.description else None,
                status,
            ),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=500, detail="Failed to create product.")

    return ProductResponse.model_validate(row)


@router.get("", response_model=list[ProductResponse])
def list_products(
    status: Optional[str] = Query(default=None, description="Filter by status: active or inactive"),
) -> list[ProductResponse]:
    """
    Public: List all products (optionally filtered by status).
    """
    with get_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT id, product_name, price, image, description, status, add_time "
                "FROM products WHERE status = %s ORDER BY add_time DESC",
                (status.lower(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, product_name, price, image, description, status, add_time "
                "FROM products ORDER BY add_time DESC"
            ).fetchall()

    return [ProductResponse.model_validate(r) for r in rows]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int) -> ProductResponse:
    """
    Public: Get a single product by ID.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, product_name, price, image, description, status, add_time "
            "FROM products WHERE id = %s",
            (product_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Product not found.")

    return ProductResponse.model_validate(row)


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    payload: ProductCreate,
    admin: dict = Depends(get_current_admin),
) -> ProductResponse:
    """
    Admin: Update an existing product.
    Requires admin Bearer token.
    """
    status = payload.status.lower()
    if status not in ("active", "inactive"):
        raise HTTPException(status_code=422, detail="status must be 'active' or 'inactive'.")

    with get_connection() as conn:
        row = conn.execute(
            """
            UPDATE products
            SET product_name = %s, price = %s, image = %s, description = %s, status = %s
            WHERE id = %s
            RETURNING id, product_name, price, image, description, status, add_time
            """,
            (
                payload.product_name.strip(),
                payload.price,
                payload.image.strip() if payload.image else None,
                payload.description.strip() if payload.description else None,
                status,
                product_id,
            ),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Product not found.")

    return ProductResponse.model_validate(row)


@router.delete("/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    admin: dict = Depends(get_current_admin),
):
    """
    Admin: Delete a product.
    Requires admin Bearer token.
    """
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM products WHERE id = %s RETURNING id", (product_id,)
        ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Product not found.")
