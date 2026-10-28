import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class SyncServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_settings = {
            "database_path": settings.database_path,
            "api_key": settings.api_key,
            "webhook_secret": settings.webhook_secret,
        }
        object.__setattr__(settings, "database_path", str(Path(self.temp_dir.name) / "test.db"))
        object.__setattr__(settings, "api_key", "test-api-key")
        object.__setattr__(settings, "webhook_secret", "test-webhook-secret")
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.headers = {"X-API-Key": settings.api_key}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        for key, value in self.original_settings.items():
            object.__setattr__(settings, key, value)
        self.temp_dir.cleanup()

    def sign(self, body: bytes) -> dict[str, str]:
        signature = hmac.new(
            settings.webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return {"X-Signature-256": signature, "Content-Type": "application/json"}

    def test_api_key_protects_product_endpoints(self):
        response = self.client.get("/api/products")
        self.assertEqual(response.status_code, 401)

        response = self.client.put(
            "/api/products",
            headers=self.headers,
            json={"sku": "SKU-1", "name": "Item", "price": 5.5, "stock": 3},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sku"], "SKU-1")

    def test_webhook_is_signed_and_idempotent(self):
        payload = {
            "event_id": "event-1",
            "source": "supplier",
            "event_type": "product.updated",
            "data": {"sku": "SKU-2", "name": "Item 2", "price": 12, "stock": 8},
        }
        body = json.dumps(payload).encode()

        first = self.client.post(
            "/webhooks/events", content=body, headers=self.sign(body)
        )
        second = self.client.post(
            "/webhooks/events", content=body, headers=self.sign(body)
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "processed")
        self.assertEqual(second.json()["status"], "duplicate")
        products = self.client.get("/api/products", headers=self.headers).json()
        self.assertEqual([product["sku"] for product in products], ["SKU-2"])

    def test_invalid_webhook_does_not_consume_event_id(self):
        invalid = {
            "event_id": "reusable-event",
            "source": "supplier",
            "event_type": "product.updated",
            "data": {},
        }
        body = json.dumps(invalid).encode()
        response = self.client.post(
            "/webhooks/events", content=body, headers=self.sign(body)
        )
        self.assertEqual(response.status_code, 422)

        invalid["data"] = {"sku": "SKU-3", "name": "Item 3", "price": 4, "stock": 1}
        body = json.dumps(invalid).encode()
        response = self.client.post(
            "/webhooks/events", content=body, headers=self.sign(body)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processed")

    def test_logistics_csv_exports_orders(self):
        self.client.put(
            "/api/orders",
            headers=self.headers,
            json={"order_id": "ORD-1", "status": "in_transit", "tracking_number": "TRACK-1"},
        )
        response = self.client.get(
            "/api/logistics/export.csv", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ORD-1,in_transit,TRACK-1", response.text)


if __name__ == "__main__":
    unittest.main()
