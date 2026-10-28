from typing import Literal

from pydantic import BaseModel, Field


class ProductInput(BaseModel):
    sku: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    price: float = Field(ge=0)
    stock: int = Field(ge=0)
    source: str = Field(default="internal", min_length=1, max_length=64)


class Product(ProductInput):
    updated_at: str


class OrderInput(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    tracking_number: str | None = Field(default=None, max_length=128)
    source: str = Field(default="internal", min_length=1, max_length=64)


class Order(OrderInput):
    updated_at: str


class EventData(BaseModel):
    sku: str | None = None
    name: str | None = None
    price: float | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    order_id: str | None = None
    status: str | None = None
    tracking_number: str | None = None


class WebhookEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=64)
    event_type: Literal["product.updated", "order.updated"]
    data: EventData
