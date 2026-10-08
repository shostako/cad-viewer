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

# 同時起動の直列化。起動アイコンを続けて 2 回押すと start.sh が 2 本走り、
# backend を 2 つ立てようとして pidfile が負けた側を指すことがある。
# 先の 1 本が終わるまで待ち、後の 1 本は「起動済み」としてブラウザを開くだけにする。
exec 9>/tmp/cadviewer.lock
if ! flock -w 300 9; then
  log "ERROR: 別の start.sh が 5 分以上終わらない（/tmp/cadviewer.lock）"
  exit 1
fi

# 0. backend venv 健全性チェック
if [ ! -x "${VENV}/bin/uvicorn" ]; then
  log "ERROR: backend venv が無い。README の手順で backend/.venv を作れ:"
  log "  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock"
  exit 1
fi

FRONT="${ROOT}/frontend"
PIDFILE=/tmp/cadviewer.pid

# 1. frontend/dist が無いか、dist より新しいソース・設定があればビルドする
#    （存在だけで判定すると、git pull 後も古い画面のまま起動してしまう）
frontend_stale() {
  [ -f "${FRONT}/dist/index.html" ] || return 0
  [ -n "$(find "${FRONT}/src" "${FRONT}/index.html" "${FRONT}/package.json" \
      "${FRONT}/package-lock.json" "${FRONT}/vite.config.ts" "${FRONT}/tsconfig.json" \
      -newer "${FRONT}/dist/index.html" -print -quit 2>/dev/null)" ]
}
# 依存は node_modules が無いか、package-lock.json が前回の install より新しければ入れ直す
deps_stale() {
  [ -f "${FRONT}/node_modules/.package-lock.json" ] || return 0
  [ "${FRONT}/package-lock.json" -nt "${FRONT}/node_modules/.package-lock.json" ]
}
if frontend_stale; then
  if deps_stale; then
    log "frontend の依存が無いか古い → npm install"
    ( cd "${FRONT}" && npm install )
  fi
  log "frontend のビルドが無いか古い → npm run build"
  ( cd "${FRONT}" && npm run build )
fi

# 2. backend
# start.sh が立てた backend で、立てた後に backend のコードか依存が変わっていれば、
# 古いコードのまま動いているので立て直す。手で立てた backend（--reload 等）には触らない。
backend_stale() {
  [ -f "${PIDFILE}" ] || return 1
  local pid
  pid="$(cat "${PIDFILE}")"
  # pid の再利用に備え、その pid が自分の uvicorn であることを確かめる
  tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null \
    | grep -qF "${VENV}/bin/uvicorn app.main:app" || return 1
  # __pycache__ は import で pidfile より後に書かれるので、*.py だけを見る
  [ -n "$(find "${ROOT}/backend/app" -name '*.py' -newer "${PIDFILE}" -print -quit 2>/dev/null)" ] \
    || [ "${ROOT}/backend/requirements.lock" -nt "${PIDFILE}" ]
}
if alive && backend_stale; then
  old_pid="$(cat "${PIDFILE}")"
  log "backend のコードが起動後に更新されている → 再起動"
  kill "${old_pid}"
  for _ in $(seq 1 20); do
    kill -0 "${old_pid}" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "${old_pid}" 2>/dev/null; then
    log "ERROR: 古い backend (pid ${old_pid}) が止まらない"
    exit 1
  fi
fi

if alive; then
  log "backend は既に起動済み"
else
  log "backend 起動中..."
  # cd を & の外に出す。`cd && nohup ... &` だと & が列全体にかかり、$! が
  # uvicorn でなく中継のサブシェルの pid になる
  ( cd "${ROOT}/backend" || exit 1
    # 9>&-: ロックの fd を uvicorn に引き継がせない（引き継ぐと backend が
    # 生きている間ずっとロックが握られ、次の start.sh が 5 分待たされる）
    nohup "${VENV}/bin/uvicorn" app.main:app --port "${PORT}" > /tmp/cadviewer.log 2>&1 9>&- &
    echo $! > "${PIDFILE}" )
  # health 待ち（最大 15 秒）
  for _ in $(seq 1 30); do
    alive && break
    sleep 0.5
  done
  if ! alive; then
    log "ERROR: backend が起動しなかった。ログ: /tmp/cadviewer.log"
    exit 1
  fi
  # 自分の uvicorn が実際にポートを持っているときだけ pidfile を残す。
  # 手で立てた別の backend が先にポートを取っていたら、それは自分の管理外。
  listener="$(ss -ltnpH "sport = :${PORT}" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true)"
  if [ "${listener}" != "$(cat "${PIDFILE}")" ]; then
    rm -f "${PIDFILE}"
  fi
  log "backend 起動完了"
fi

# 3. Windows 側の既定ブラウザで開く（WSL からは cmd.exe 経由）
cmd.exe /c start "" "${URL}" >/dev/null 2>&1 || true
log "起動完了 → ${URL}"
