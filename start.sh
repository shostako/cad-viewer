#!/usr/bin/env bash
# cad-viewer ワンショット起動。
#
# frontend を同梱した backend を 1 プロセス(:8008)で立て、Windows 側ブラウザを
# 開く。冪等 — 既に起動していればビルドも再起動もせず、ブラウザを開くだけ。
# 途中で失敗しても、再実行すれば続きから完了できる（リトライ安全）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8008
# 127.0.0.1 固定（localhost だと Windows 側で ::1(IPv6) が先に解決され、IPv4 しか
# 聴いていない uvicorn に届かず黒穴タイムアウトする — mirrored モードで実害あり）
URL="http://127.0.0.1:${PORT}"
VENV="${ROOT}/backend/.venv"

log() { printf '[cad-viewer] %s\n' "$1"; }

# health 確認。--connect-timeout 必須: WSL の mirrored モードでは誰も聴いていない
# 127.0.0.1 のポートへの接続が拒否されず黒穴になり、素の curl は 2 分以上返らない。
alive() { curl -sf --connect-timeout 1 -m 3 "${URL}/api/health" >/dev/null 2>&1; }

# 0. backend venv 健全性チェック
if [ ! -x "${VENV}/bin/uvicorn" ]; then
  log "ERROR: backend venv が無い。README の手順で backend/.venv を作れ:"
  log "  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock"
  exit 1
fi

# 1. frontend/dist が無ければビルド（node_modules が前提）
if [ ! -f "${ROOT}/frontend/dist/index.html" ]; then
  if [ ! -d "${ROOT}/frontend/node_modules" ]; then
    log "frontend の依存が無い → npm install"
    ( cd "${ROOT}/frontend" && npm install )
  fi
  log "frontend 未ビルド → npm run build"
  ( cd "${ROOT}/frontend" && npm run build )
fi

# 2. backend が既に応答するなら起動不要（冪等）
if alive; then
  log "backend は既に起動済み"
else
  log "backend 起動中..."
  ( cd "${ROOT}/backend" && nohup "${VENV}/bin/uvicorn" app.main:app --port "${PORT}" \
      > /tmp/cadviewer.log 2>&1 & )
  # health 待ち（最大 15 秒）
  for _ in $(seq 1 30); do
    alive && break
    sleep 0.5
  done
  if ! alive; then
    log "ERROR: backend が起動しなかった。ログ: /tmp/cadviewer.log"
    exit 1
  fi
  log "backend 起動完了"
fi

# 3. Windows 側の既定ブラウザで開く（WSL からは cmd.exe 経由）
cmd.exe /c start "" "${URL}" >/dev/null 2>&1 || true
log "起動完了 → ${URL}"
