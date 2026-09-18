# M5 — Local Unix-Socket Ingestion (Post-v1)

**Type:** Post-v1 enhancement  
**Depends on:** M2b  
**Unlocks:** —  
**Goal:** Accept the existing ingest HTTP API on an additional local Unix socket without creating a second application lifecycle.

## Scope

This socket is a client-to-ingest transport and is distinct from the ingest-to-processor IPC socket. It does not alter event schemas, UTC handling, authentication, queues, IPC framing, processor behavior, or sinks.

Use one Uvicorn server/application lifecycle with pre-bound TCP and Unix sockets passed as the server's socket list. Do not start nested Uvicorn servers inside FastAPI lifespan; that would duplicate startup/shutdown hooks and background writer tasks.

```text
INGEST_UNIX_SOCKET_ENABLED=false
INGEST_UNIX_SOCKET_PATH=/var/run/telemetria/ingest.sock
INGEST_UNIX_SOCKET_MODE=0660
```

Startup validates the parent directory, safely handles a stale socket, binds both configured listeners, and applies permissions. Shutdown closes both and unlinks only the socket created by this process. Compose mounting and ownership are explicit when enabled.

## Acceptance criteria

- [ ] TCP and Unix-socket clients receive identical status codes and response bodies for the same request.
- [ ] The application lifespan and IPC writer start exactly once.
- [ ] Stale-socket, permission, collision, shutdown cleanup, and disabled-mode behavior are tested.
- [ ] HTTP-over-UDS integration tests cover single and batch ingestion.
- [ ] M5 remains excluded from v1 completion criteria.
