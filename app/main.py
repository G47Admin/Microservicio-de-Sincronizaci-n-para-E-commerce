import csv
import hashlib
import hmac
import io
import sqlite3
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.security import APIKeyHeader
from pydantic import ValidationError

from app.config import settings
from app.database import connection, initialize_database
from app.integrations import deliver
from app.schemas import Order, OrderInput, Product, ProductInput, WebhookEvent

app = FastAPI(
    title="E-commerce Sync Service",
    description="Sincroniza catálogo, inventario y estados de pedidos entre sistemas REST.",
    version="1.0.0",
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


def require_api_key(api_key: str | None = Depends(api_key_header)) -> None:
    if not api_key or not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def product_from_row(row) -> Product:
    return Product(**dict(row))


def order_from_row(row) -> Order:
    return Order(**dict(row))


def _upsert_product(conn: sqlite3.Connection, product: ProductInput, timestamp: str):
    conn.execute(
        """
        INSERT INTO products (sku, name, price, stock, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            name = excluded.name,
            price = excluded.price,
            stock = excluded.stock,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (product.sku, product.name, product.price, product.stock, product.source, timestamp),
    )
    return conn.execute("SELECT * FROM products WHERE sku = ?", (product.sku,)).fetchone()


def _upsert_order(conn: sqlite3.Connection, order: OrderInput, timestamp: str):
    conn.execute(
        """
        INSERT INTO orders (order_id, status, tracking_number, source, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(order_id) DO UPDATE SET
            status = excluded.status,
            tracking_number = excluded.tracking_number,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (order.order_id, order.status, order.tracking_number, order.source, timestamp),
    )
    return conn.execute("SELECT * FROM orders WHERE order_id = ?", (order.order_id,)).fetchone()


def save_product(product: ProductInput, updated_at: str | None = None) -> Product:
    timestamp = updated_at or utc_now()
    with connection() as conn:
        row = _upsert_product(conn, product, timestamp)
    return product_from_row(row)


def save_order(order: OrderInput, updated_at: str | None = None) -> Order:
    timestamp = updated_at or utc_now()
    with connection() as conn:
        row = _upsert_order(conn, order, timestamp)
    return order_from_row(row)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/products", response_model=list[Product], dependencies=[Depends(require_api_key)])
def list_products() -> list[Product]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
    return [product_from_row(row) for row in rows]


@app.put("/api/products", response_model=Product, dependencies=[Depends(require_api_key)])
def upsert_product(product: ProductInput) -> Product:
    return save_product(product)


@app.get("/api/orders", response_model=list[Order], dependencies=[Depends(require_api_key)])
def list_orders() -> list[Order]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY updated_at DESC").fetchall()
    return [order_from_row(row) for row in rows]


@app.put("/api/orders", response_model=Order, dependencies=[Depends(require_api_key)])
def upsert_order(order: OrderInput) -> Order:
    return save_order(order)


@app.post("/api/sync/{resource}", dependencies=[Depends(require_api_key)])
async def sync_resource(resource: str) -> dict:
    if resource not in {"products", "orders"}:
        raise HTTPException(status_code=404, detail="Unsupported resource")

    with connection() as conn:
        rows = conn.execute(f"SELECT * FROM {resource} ORDER BY updated_at").fetchall()
    payload = [dict(row) for row in rows]
    try:
        result = await deliver(resource, {"items": payload})
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"Downstream sync failed: {exc}") from exc
    return {"resource": resource, "count": len(payload), **result}


@app.get("/api/logistics/export.csv", dependencies=[Depends(require_api_key)])
def export_logistics_csv() -> Response:
    with connection() as conn:
        rows = conn.execute(
            "SELECT order_id, status, tracking_number, source, updated_at FROM orders ORDER BY updated_at DESC"
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["order_id", "status", "tracking_number", "source", "updated_at"])
    writer.writerows([tuple(row) for row in rows])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="orders-logistics.csv"'},
    )


@app.post("/webhooks/events")
async def receive_event(
    request: Request,
    x_signature_256: str | None = Header(default=None, alias="X-Signature-256"),
) -> dict:
    if not settings.webhook_secret:
        raise HTTPException(status_code=503, detail="WEBHOOK_SECRET is not configured")

    body = await request.body()
    expected_signature = hmac.new(
        settings.webhook_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    supplied_signature = (x_signature_256 or "").removeprefix("sha256=")
    if not hmac.compare_digest(expected_signature, supplied_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        event = WebhookEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    now = utc_now()
    product = None
    order = None
    if event.event_type == "product.updated":
        if not event.data.sku or event.data.name is None or event.data.price is None or event.data.stock is None:
            raise HTTPException(status_code=422, detail="Product events require sku, name, price and stock")
        product = ProductInput(
            sku=event.data.sku,
            name=event.data.name,
            price=event.data.price,
            stock=event.data.stock,
            source=event.source,
        )
    else:
        if not event.data.order_id or not event.data.status:
            raise HTTPException(status_code=422, detail="Order events require order_id and status")
        order = OrderInput(
            order_id=event.data.order_id,
            status=event.data.status,
            tracking_number=event.data.tracking_number,
            source=event.source,
        )

    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO processed_events (event_id, source, event_type, received_at) VALUES (?, ?, ?, ?)",
                (event.event_id, event.source, event.event_type, now),
            )
            if product:
                _upsert_product(conn, product, now)
            else:
                _upsert_order(conn, order, now)
    except sqlite3.IntegrityError as exc:
        if "processed_events.event_id" in str(exc):
            return {"status": "duplicate", "event_id": event.event_id}
        raise
    return {"status": "processed", "event_id": event.event_id}
