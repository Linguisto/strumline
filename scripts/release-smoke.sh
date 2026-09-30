#!/usr/bin/env bash
set -euo pipefail

project_name="${COMPOSE_PROJECT_NAME:-strumline-release-smoke}"
image_tag="${STRUMLINE_IMAGE_TAG:-release-candidate}"
env_file="${SMOKE_ENV_FILE:-.env}"
marker="strumline-smoke-$(date -u +%Y%m%dT%H%M%SZ)-$$"

if [[ ! -f "$env_file" ]]; then
  echo "Smoke environment file not found: $env_file" >&2
  exit 2
fi
if ! grep -Eq '^APP_KEY=.+$' "$env_file" || ! grep -Eq '^INGEST_DB_PASSWORD=.+$' "$env_file"; then
  echo "APP_KEY and INGEST_DB_PASSWORD must be populated in $env_file" >&2
  exit 2
fi

compose=(
  docker compose
  --project-name "$project_name"
  --env-file "$env_file"
  --file compose.yaml
  --file docker/compose.release-smoke.yaml
)

cleanup() {
  if [[ "${KEEP_SMOKE_STACK:-0}" != "1" ]]; then
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

export STRUMLINE_IMAGE_TAG="$image_tag"
export STRUMLINE_TARGET=runtime

"${compose[@]}" up --detach postgres loki
"${compose[@]}" run --rm strumline-cli strumline migrate >/dev/null
"${compose[@]}" run --rm strumline-cli python -m strumline.db.bootstrap >/dev/null
"${compose[@]}" up --detach api ingest processor

for endpoint in 8000 8001 8002; do
  for _ in {1..60}; do
    if curl --fail --silent "http://127.0.0.1:${endpoint}/health" >/dev/null; then
      break
    fi
    sleep 1
  done
  curl --fail --silent "http://127.0.0.1:${endpoint}/health" >/dev/null
done

started_at=$(date +%s)
"${compose[@]}" run --rm strumline-cli \
  strumline project create smoke --name "Release smoke" >/dev/null
app_output=$("${compose[@]}" run --rm strumline-cli \
  strumline app create smoke walkthrough --name "Walkthrough")
token=$(printf '%s' "$app_output" | grep -Eo '[A-Za-z0-9_-]{43}' | head -n 1)
unset app_output
if [[ -z "$token" ]]; then
  echo "Could not extract the one-time app token" >&2
  exit 1
fi

response=$(curl --fail --silent http://127.0.0.1:8001/v1/logs \
  -H "x-strumline-token: $token" \
  -H 'Content-Type: application/json' \
  --data "{\"resourceLogs\":[{\"scopeLogs\":[{\"logRecords\":[{\"severityNumber\":9,\"body\":{\"stringValue\":\"$marker\"}}]}]}]}")
unset token
if [[ "$response" != "{}" ]]; then
  echo "Ingest did not return complete success: $response" >&2
  exit 1
fi

deadline=$((started_at + 300))
while (( $(date +%s) < deadline )); do
  result=$(curl --fail --silent --get http://127.0.0.1:3100/loki/api/v1/query_range \
    --data-urlencode 'query={project="smoke",app="walkthrough"}' \
    --data-urlencode 'limit=20')
  if [[ "$result" == *"$marker"* ]]; then
    elapsed=$(( $(date +%s) - started_at ))
    echo "Release smoke passed in ${elapsed}s: resource creation -> HTTP ingest -> Loki observation"
    echo "Marker: $marker"
    exit 0
  fi
  sleep 2
done

echo "Release smoke timed out after 300s waiting for the exact Loki marker" >&2
exit 1
