"""_queue_io.py — リリース候補キューの安全な読み書き(並行プロセス対策)。

cron(idol_wiki_release_daily.sh)と手動(review_queue --approve)が候補キューを
同時に書くと、全書き換え(write_text)では片方の変更が消える(applied→pending 巻き戻り等)。
これを防ぐため:
  - fcntl.flock で排他ロック
  - 全書き換えでなく candidate_id 単位のマージ更新(ディスク最新を読み直し、
    変更した候補だけ上書き、未知の候補はディスク側を保持)
"""
from __future__ import annotations
import fcntl
import json
from pathlib import Path

CANDIDATES = Path(__file__).resolve().parents[3] / "data" / "idol_wiki_release_candidates.jsonl"


def load() -> list[dict]:
    if not CANDIDATES.exists():
        return []
    return [json.loads(l) for l in CANDIDATES.read_text().splitlines() if l.strip()]


def merge_update(updated: list[dict]) -> None:
    """updated 内の候補(candidate_id 一致)だけをディスクへ反映する。

    flock 下でディスク最新を読み直してから updated の差分をマージするので、
    並行プロセスが別候補を変更していても消えない。updated に無い候補は保持。
    """
    by_id = {c["candidate_id"]: c for c in updated if c.get("candidate_id")}
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    # r+ で開けるよう、無ければ作る
    if not CANDIDATES.exists():
        CANDIDATES.write_text("")
    with CANDIDATES.open("r+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            disk = [json.loads(l) for l in fh.read().splitlines() if l.strip()]
            seen = set()
            out = []
            for c in disk:
                cid = c.get("candidate_id")
                seen.add(cid)
                out.append(by_id.get(cid, c))  # 自分が更新した候補なら差し替え
            # ディスクに無い新規候補(updated 側にのみ存在)も追加
            for cid, c in by_id.items():
                if cid not in seen:
                    out.append(c)
            fh.seek(0)
            fh.truncate()
            fh.write("\n".join(json.dumps(c, ensure_ascii=False) for c in out) + "\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
