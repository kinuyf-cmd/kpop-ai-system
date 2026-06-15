#!/bin/bash
# ============================================================
# refresh_ca_bundle.sh — popup fetcher 用 CA バンドル生成
#
# 背景:
#   kbuzzlab.com は Let's Encrypt の新ルート "ISRG Root YR" を採用。
#   このルートは 2025-09 生成で、まだ OS/certifi の信頼ストアに未収録。
#   そのため popup_event_fetcher.py の TLS 検証が落ち、2026-05 以降
#   kbuzzlab 由来の popup 取得が停止していた。
#
# 対策:
#   certifi バンドル + Root YR(X1クロス署名 + 自己署名)を結合した
#   data/ca/kpop_ca_bundle.pem を生成。fetcher はこれを cafile に使う。
#
# 再生成タイミング:
#   - Root YR が公式トラストストアに収録されたら本対応は不要(削除可)
#   - certifi を更新したとき(pip 更新後)に再実行して取り込む
#
# 使い方:  bash tools/refresh_ca_bundle.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

CA_DIR="data/ca"
BUNDLE="${CA_DIR}/kpop_ca_bundle.pem"
PY="venv_kpi/bin/python3"
[[ -x "$PY" ]] || PY="python3"

mkdir -p "$CA_DIR"

echo "[1/3] Let's Encrypt Root YR 証明書を取得"
curl -fsS -o "${CA_DIR}/root-yr-by-x1.pem" https://letsencrypt.org/certs/gen-y/root-yr-by-x1.pem
curl -fsS -o "${CA_DIR}/root-yr.pem"       https://letsencrypt.org/certs/gen-y/root-yr.pem

echo "[2/3] certifi + Root YR を結合"
"$PY" - "$BUNDLE" <<'PYEOF'
import certifi, pathlib, sys
out = pathlib.Path(sys.argv[1])
parts = [
    pathlib.Path(certifi.where()).read_text(),
    pathlib.Path("data/ca/root-yr-by-x1.pem").read_text(),
    pathlib.Path("data/ca/root-yr.pem").read_text(),
]
out.write_text("\n".join(parts))
print(f"  wrote {out} ({out.stat().st_size} bytes)")
PYEOF

echo "[3/3] kbuzzlab で接続検証"
"$PY" - "$BUNDLE" <<'PYEOF'
import ssl, urllib.request, sys
ctx = ssl.create_default_context(cafile=sys.argv[1])
r = urllib.request.urlopen("https://kbuzzlab.com/popup_event-sitemap.xml", timeout=20, context=ctx)
assert r.status == 200, r.status
print(f"  OK kbuzzlab status={r.status}")
PYEOF

echo "完了: $BUNDLE"
