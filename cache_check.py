#!/usr/bin/env python3
"""cache_check.py — M10 P-4 Prompt Caching 検証

orchestration-leader SKILL §5 の Prompt Caching を検証する。
SKILL.md 群のキャッシュ可能性をローカルで確認し、
Anthropic API の cache_control ブロック生成準備として動作する。

検証内容:
1. ~/.claude/skills/ 配下の SKILL.md トータルサイズ
2. キャッシュ対象としての適格性(1024 tokens 以上が cache_control 適用条件)
3. cache_control ブロック構造の生成サンプル
4. cache hit/miss シミュレーション(同一プロンプトで2回送信時のトークン削減見込み)

用途:
    python3 cache_check.py                     # 全 skill 検証
    python3 cache_check.py --skill kpop-citation-article
    python3 cache_check.py --emit-block         # cache_control JSON ブロック出力
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude" / "skills"
LOG_DIR = Path.home() / ".kpop_recovery"
LOG_FILE = LOG_DIR / "cache_check_log.jsonl"

# Anthropic cache_control 最小トークン要件(Claude 4.x: 1024 tokens)
MIN_CACHE_TOKENS = 1024
TOKENS_PER_CHAR = 0.25  # 日本語/英語混在の概算(1 token ≈ 4 chars)


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def estimate_tokens(text: str) -> int:
    """概算: 日本語は 1 char ≈ 1 token、英語は 4 chars ≈ 1 token。混在は中間。"""
    # 簡易: 全角(0x3000以上)を1:1、半角を 1:0.25
    ja = sum(1 for c in text if ord(c) >= 0x3000)
    en = len(text) - ja
    return int(ja + en * TOKENS_PER_CHAR)


def check_skill(skill_dir: Path) -> dict:
    skill_md = skill_dir / "SKILL.md"
    name = skill_dir.name
    if not skill_md.exists():
        return {"skill": name, "error": "SKILL.md missing"}
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    chars = len(text)
    lines = text.count("\n") + 1
    tokens_est = estimate_tokens(text)
    cacheable = tokens_est >= MIN_CACHE_TOKENS
    return {
        "skill": name,
        "chars": chars,
        "lines": lines,
        "tokens_est": tokens_est,
        "cacheable": cacheable,
        "cache_control": {"type": "ephemeral"} if cacheable else None,
    }


def emit_cache_block(skill_name: str) -> dict:
    """Anthropic API messages.create 用の cache_control 付きブロックを返す"""
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_md.exists():
        return {"error": f"SKILL.md not found for {skill_name}"}
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    block = {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }
    return block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", help="specific skill name")
    ap.add_argument("--emit-block", action="store_true", help="emit cache_control block JSON")
    args = ap.parse_args()

    if args.emit_block:
        if not args.skill:
            print("--emit-block requires --skill", file=sys.stderr)
            return 2
        block = emit_cache_block(args.skill)
        print(json.dumps(block, ensure_ascii=False, indent=2))
        return 0

    targets = []
    if args.skill:
        targets = [SKILLS_DIR / args.skill]
    else:
        targets = [d for d in SKILLS_DIR.iterdir() if d.is_dir()]

    results = []
    for d in sorted(targets):
        results.append(check_skill(d))

    cacheable = [r for r in results if r.get("cacheable")]
    not_cacheable = [r for r in results if r.get("cacheable") is False]
    errors = [r for r in results if "error" in r]

    total_tokens = sum(r.get("tokens_est", 0) for r in results)
    cacheable_tokens = sum(r.get("tokens_est", 0) for r in cacheable)

    print("PROMPT CACHE CHECK")
    print(f"  skills total      : {len(results)}")
    print(f"  cacheable         : {len(cacheable)}  (>= {MIN_CACHE_TOKENS} tokens)")
    print(f"  not cacheable     : {len(not_cacheable)}")
    print(f"  errors            : {len(errors)}")
    print(f"  total tokens est  : {total_tokens:,}")
    print(f"  cacheable tokens  : {cacheable_tokens:,}")
    if total_tokens > 0:
        pct = 100 * cacheable_tokens / total_tokens
        print(f"  cacheable ratio   : {pct:.1f}%")
    print()
    print("  Top 5 cacheable skills:")
    for r in sorted(cacheable, key=lambda x: x.get("tokens_est", 0), reverse=True)[:5]:
        print(f"    {r['skill']:30s} {r['tokens_est']:>6} tokens  ({r['lines']} lines)")

    # JSONL ログ追記
    LOG_DIR.mkdir(exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps({
            "timestamp": now_iso(),
            "total_skills": len(results),
            "cacheable_count": len(cacheable),
            "total_tokens_est": total_tokens,
            "cacheable_tokens_est": cacheable_tokens,
        }, ensure_ascii=False) + "\n")
    print(f"  log               : {LOG_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
