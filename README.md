# E-commerce Sync Service

Microservicio en Python/FastAPI para mantener un catálogo y estados de pedidos normalizados entre una tienda, proveedores, couriers y logística.

## Funcionalidades

- API REST protegida con `X-API-Key` para consultar y actualizar productos y pedidos.
- Webhook firmado con HMAC-SHA256 e idempotencia por `event_id`.
- Persistencia SQLite.
- Sincronización saliente a un endpoint REST configurable.
- Exportación CSV de pedidos para logística.
- Contenedor Docker y volumen persistente.

## Ejecutar con Docker

```powershell
Copy-Item .env.example .env
```

Edite `.env` y configure claves seguras antes de iniciar el servicio:

```powershell
docker compose up --build
```

La API queda disponible en `http://localhost:8000`; la documentación interactiva está en `/docs`.

## Ejecutar localmente

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:API_KEY = "local-development-key"
$env:WEBHOOK_SECRET = "local-webhook-secret"
uvicorn app.main:app --reload
```

## API

Las rutas `/api/*` requieren `X-API-Key` igual a `API_KEY`.

```powershell
$headers = @{ "X-API-Key" = "local-development-key" }
$product = @{
  sku = "CAMISETA-001"
  name = "Camiseta"
  price = 19.9
  stock = 12
  source = "supplier"
} | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri http://localhost:8000/api/products -Headers $headers -ContentType "application/json" -Body $product
```

- `GET /api/products`, `PUT /api/products`
- `GET /api/orders`, `PUT /api/orders`
- `POST /api/sync/products` y `POST /api/sync/orders`: envían `{ "items": [...] }` a `SYNC_TARGET_URL/products` o `/orders`. El destino opcional puede exigir `SYNC_TARGET_TOKEN`.
- `GET /api/logistics/export.csv`: descarga los pedidos para planillas/logística.
- `POST /webhooks/events`: recibe eventos normalizados de producto o pedido.

### Formato webhook

El remitente calcula HMAC-SHA256 sobre los bytes exactos del JSON y lo envía en `X-Signature-256` como hexadecimal (o `sha256=<hex>`). `WEBHOOK_SECRET` debe coincidir.

```json
{
  "event_id": "shopify-evt-0001",
  "source": "shopify",
  "event_type": "product.updated",
  "data": {
    "sku": "CAMISETA-001",
    "name": "Camiseta",
    "price": 19.9,
    "stock": 12
  }
}
```

Para pedidos, use `event_type: "order.updated"` y los campos `order_id`, `status` y opcionalmente `tracking_number`. Un mismo `event_id` solo se procesa una vez.

## Integraciones

El servicio define un contrato común en JSON, de modo que Shopify, un proveedor, una pasarela o un courier se conectan mediante webhooks y adaptadores REST que traduzcan sus formatos al contrato. La URL saliente es un endpoint de integración genérico: Shopify y otros servicios pueden requerir una traducción de payload y rutas específicas; no se asume que aceptan directamente el formato común.

Antes de producción: configure secretos únicos, HTTPS, políticas de red y límites de tasa; adapte/valide los payloads concretos del proveedor y configure sus webhooks para el contrato anterior.
