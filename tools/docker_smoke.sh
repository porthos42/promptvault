#!/usr/bin/env bash
# Smoke test for a Prompt Vault image: health, seed library, non-root, persistence across a
# restart, export, graceful stop and image size. Only touches the container and volume it
# creates (names derive from PV_SMOKE_NAME).
#
#   tools/docker_smoke.sh IMAGE [HOST_PORT]
#
# Env: PV_SMOKE_NAME (default pv-smoke), PV_MAX_IMAGE_MB (default 200), PV_EXPECT_XLSX (default 1),
#      PV_SMOKE_KEEP=1 keeps the container and volume for inspection.
set -euo pipefail

IMAGE="${1:?usage: docker_smoke.sh IMAGE [HOST_PORT]}"
PORT="${2:-18080}"
NAME="${PV_SMOKE_NAME:-pv-smoke}"
VOL="${NAME}-data"
MAX_MB="${PV_MAX_IMAGE_MB:-200}"
BASE="http://localhost:${PORT}/api/v1"

cleanup() {
  if [ "${PV_SMOKE_KEEP:-0}" != "1" ]; then
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOL" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; docker logs "$NAME" 2>&1 | tail -40 >&2 || true; exit 1; }
ok() { echo "ok:   $*"; }

wait_healthy() {
  for _ in $(seq 1 60); do
    if curl -fsS "$BASE/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  fail "no healthy response from $BASE/health within 60 s"
}

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker volume rm "$VOL" >/dev/null 2>&1 || true
docker volume create "$VOL" >/dev/null
# the same restrictions the compose files use: read-only root, no capabilities, no new privileges
docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:8080" -v "$VOL:/data" \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges "$IMAGE" >/dev/null

wait_healthy
ok "health answers: $(curl -fsS "$BASE/health")"
ok "version: $(curl -fsS "$BASE/version")"

uid="$(docker exec "$NAME" id -u)"
[ "$uid" != "0" ] || fail "container runs as root"
ok "runs as uid $uid"

listing="$(docker exec "$NAME" promptvault list --limit 500)"
grep -q "Resume Bullet Rewriter" <<<"$listing" || fail "seed library not loaded"
ok "seed library loaded ($(wc -l <<<"$listing" | tr -d ' ') lines in list)"

curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"title":"Smoke persistence check","body":"This prompt must survive a restart."}' \
  "$BASE/prompts" >/dev/null || fail "creating a prompt failed"
ok "created a prompt"

docker restart "$NAME" >/dev/null
wait_healthy
listing="$(docker exec "$NAME" promptvault list --limit 500)"
grep -q "Smoke persistence check" <<<"$listing" || fail "prompt lost after restart"
grep -q "Resume Bullet Rewriter" <<<"$listing" || fail "seed prompts lost after restart"
ok "data survives a restart"

export_json="$(docker exec "$NAME" promptvault export json -)"
grep -q "Smoke persistence check" <<<"$export_json" || fail "export json does not contain the new prompt"
ok "export json works ($(wc -c <<<"$export_json" | tr -d ' ') bytes)"

if [ "${PV_EXPECT_XLSX:-1}" = "1" ]; then
  docker exec "$NAME" promptvault export xlsx /tmp/smoke.xlsx >/dev/null || fail "export xlsx failed"
  ok "export xlsx works (extra installed)"
fi

start=$(date +%s)
docker stop "$NAME" >/dev/null
secs=$(( $(date +%s) - start ))
code="$(docker inspect --format '{{.State.ExitCode}}' "$NAME")"
[ "$code" = "0" ] || fail "container exit code $code after docker stop (graceful shutdown expected 0)"
ok "graceful stop: exit code 0 after ${secs}s"

bytes="$(docker image inspect --format '{{.Size}}' "$IMAGE")"
mb=$(( bytes / 1000000 ))
echo "image size: ${mb} MB (ceiling ${MAX_MB} MB)"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  echo "- \`$IMAGE\`: ${mb} MB uncompressed (ceiling ${MAX_MB} MB)" >>"$GITHUB_STEP_SUMMARY"
fi
[ "$mb" -le "$MAX_MB" ] || fail "image is ${mb} MB, above the ${MAX_MB} MB ceiling"
echo "SMOKE TEST PASSED"
