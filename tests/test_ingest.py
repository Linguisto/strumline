"""Public ingestion surface and executable OpenAPI examples."""

import pytest
from httpx2 import ASGITransport, AsyncClient

from tests.test_otlp import make_app

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path", ["/v1/ingest", "/v1/ingest/batch"])
async def test_removed_routes_return_404(path):
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json={"message": "hello"})
    assert response.status_code == 404
    assert app.state.queue.empty()
    app.state.resolver.resolve.assert_not_called()


@pytest.mark.parametrize("example,count", [("single", 1), ("batch", 2)])
async def test_openapi_examples_are_valid_exports(example, count):
    app = make_app(api_docs_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        schema = (await client.get("/openapi.json")).json()
        assert {path for path, methods in schema["paths"].items() if "post" in methods} == {
            "/v1/logs"
        }
        operation = schema["paths"]["/v1/logs"]["post"]
        token = next(p for p in operation["parameters"] if p["name"] == "x-telemetria-token")
        assert token["required"] is True
        assert set(operation["responses"]) == {"200", "400", "401", "413", "415", "503"}
        body = operation["requestBody"]["content"]["application/json"]["examples"][example]["value"]
        response = await client.post("/v1/logs", json=body, headers={"x-telemetria-token": "test"})
        assert response.status_code == 200
        assert (
            response.json()
            == operation["responses"]["200"]["content"]["application/json"]["examples"]["success"][
                "value"
            ]
        )
        assert app.state.queue.qsize() == count
        assert (await client.get("/")).status_code == 200


async def test_ingest_documentation_disabled_by_default():
    app = make_app(api_docs_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/openapi.json")).status_code == 404
        assert (await client.get("/")).status_code == 404
