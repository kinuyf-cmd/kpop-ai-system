#!/usr/bin/env bash
# 全29 popup に popup_reservation / popup_benefit を冪等設定(オーナー実行)。
# backup-first: 適用前に対象2キーの現状を SQL ダンプして保存 → apply → 件数確認。
# 触るのは popup_reservation / popup_benefit の2キーのみ。a8/外部リンク/出典/本文は不変。
#
#   sudo -u www-data bash apply_popup_reservation_benefit_29.sh
#
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
TS=$(date +%Y%m%d_%H%M%S)
# www-data 実行のため www-data 書込可能な場所へ。BACKUP_DIR で上書き可。
BACKUP_DIR="${BACKUP_DIR:-/tmp}"
BK="${BACKUP_DIR}/backup_popup_resv_benefit_${TS}.sql"

echo "=== [1/4] backup: popup_reservation / popup_benefit の現状 → $BK ==="
python3 - "$BK" <<'PY'
import sys, lib.popup_event_to_post as P
import set_popup_reservation_benefit as S
ids = S.popup_post_ids()
lines = ["-- backup popup_reservation/popup_benefit (rollback用)"]
for pid in ids:
    for k in ("popup_reservation","popup_benefit"):
        v = S.get_meta(pid, k).replace("\\","\\\\").replace("'","''")
        # 既存が空なら rollback は DELETE、非空なら現値へ UPDATE
        if v:
            lines.append(f"-- {pid} {k} 既存値あり → rollbackは下記UPSERT")
            lines.append(f"INSERT INTO wp_postmeta (post_id,meta_key,meta_value) VALUES ({pid},'{k}','{v}') ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value);")
        else:
            lines.append(f"-- {pid} {k} 既存空 → rollbackは DELETE")
            lines.append(f"DELETE FROM wp_postmeta WHERE post_id={pid} AND meta_key='{k}';")
open(sys.argv[1],"w").write("\n".join(lines)+"\n")
print(f"  backup {len(ids)}件×2キー 書き出し完了")
PY

echo "=== [2/4] dry-run 再確認(適用直前) ==="
DRY_RUN=1 python3 set_popup_reservation_benefit.py | tail -3

echo "=== [3/4] APPLY(DB書込) ==="
DRY_RUN=0 python3 set_popup_reservation_benefit.py | tail -5

echo "=== [4/4] 適用後 件数確認(非空 popup_reservation / popup_benefit) ==="
python3 - <<'PY'
import set_popup_reservation_benefit as S
ids = S.popup_post_ids()
r = sum(1 for p in ids if S.get_meta(p,"popup_reservation"))
b = sum(1 for p in ids if S.get_meta(p,"popup_benefit"))
print(f"  popup_reservation 非空={r} / popup_benefit 非空={b} (全{len(ids)}件中)")
for pid in (606,595,392):
    print(f"  [{pid}] resv={S.get_meta(pid,'popup_reservation')!r} benefit={S.get_meta(pid,'popup_benefit')!r}")
PY
echo "=== 完了。rollbackは $BK を mysql に流す ==="
