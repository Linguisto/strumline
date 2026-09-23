"""Optional real Collector interoperability: set OTELCOL_BINARY to an otelcol binary."""

from __future__ import annotations

import asyncio
import os
import socket

import pytest
from httpx2 import AsyncClient, ConnectError

from tests.test_otlp import encode, live_ingest, logs_request, make_app

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("encoding", ["proto", "json"])
async def test_collector_exports_logs(tmp_path, encoding):
    binary = os.environ.get("OTELCOL_BINARY")
    if not binary:
        pytest.skip("Set OTELCOL_BINARY to run real Collector interoperability")
    app = make_app()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    async with live_ingest(app) as endpoint:
        config = tmp_path / "collector.yaml"
        config.write_text(f"""
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:{port}
exporters:
  otlphttp:
    logs_endpoint: {endpoint}
    encoding: {encoding}
    compression: gzip
    headers:
      x-strumline-token: test-token
    sending_queue:
      enabled: false
service:
  telemetry:
    metrics:
      level: none
  pipelines:
    logs:
      receivers: [otlp]
      exporters: [otlphttp]
""")
        with (tmp_path / "collector.log").open("wb") as output:
            process = await asyncio.create_subprocess_exec(
                binary,
                "--config",
                str(config),
                stdout=output,
                stderr=output,
            )
            try:
                async with asyncio.timeout(15), AsyncClient() as client:
                    while True:
                        try:
                            response = await client.post(
                                f"http://127.0.0.1:{port}/v1/logs",
                                content=encode(logs_request(), "application/json"),
                                headers={"content-type": "application/json"},
                            )
                            break
                        except ConnectError:
                            assert process.returncode is None, (
                                tmp_path / "collector.log"
                            ).read_text()
                            await asyncio.sleep(0.05)
                    assert response.status_code == 200, response.text
                    while app.state.queue.empty():
                        await asyncio.sleep(0.01)
                event = app.state.queue.get_nowait()
                assert event.message == "payment failed"
                assert event.payload["otlp"]["logRecord"]["timeUnixNano"] == "1726668000123456789"
                assert (
                    event.payload["otlp"]["logRecord"]["traceId"]
                    == "aabbccddeeff00112233445566778899"
                )
            finally:
                if process.returncode is None:
                    process.terminate()
                await asyncio.wait_for(process.wait(), 5)
