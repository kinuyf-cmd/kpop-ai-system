
try:
    from lib.agent_learning_loop import get_recent_lessons
except: get_recent_lessons = lambda *a, **k: []
#!/usr/bin/env python3
"""DALL-E 3 を使ったサムネ画像生成

Usage:
    from lib.dalle_thumbnail_gen import generate_thumbnail
    result = generate_thumbnail(prompt="...", output_path="/tmp/thumb.png")
"""
import base64
import json
import os
import urllib.request
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

DALLE_API = "https://api.openai.com/v1/images/generations"
# 2026-05-15: dall-e-3 が OpenAI で廃止 ("model 'dall-e-3' does not exist")。
# gpt-image-1 に移行。応答は b64_json (URL 形式は廃止)。
MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
DAILY_LIMIT = 50
COST_LOG = "/home/aiuser/kpop-ai-system/logs/dalle_cost.jsonl"

# legacy dall-e-3 引数 → gpt-image-1 引数 へのマッピング (呼び出し側 API 互換維持)
_SIZE_MAP = {
    "1024x1024": "1024x1024",
    "1792x1024": "1536x1024",  # landscape
    "1024x1792": "1024x1536",  # portrait
}
_QUALITY_MAP = {
    "standard": "medium",
    "hd": "high",
}


def _count_today():
    today = date.today().isoformat()
    if not os.path.exists(COST_LOG):
        return 0
    cnt = 0
    with open(COST_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get("date") == today:
                    cnt += 1
            except Exception:
                pass
    return cnt


def _log_usage(prompt: str, cost: float, size: str, quality: str):
    os.makedirs(os.path.dirname(COST_LOG), exist_ok=True)
    with open(COST_LOG, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "date": date.today().isoformat(),
                    "ts": datetime.now().isoformat(),
                    "cost_usd": cost,
                    "size": size,
                    "quality": quality,
                    "prompt_head": prompt[:200],
                }
            )
            + "\n"
        )


def generate_thumbnail(
    prompt: str,
    output_path: str,
    size: str = "1792x1024",
    quality: str = "standard",
) -> dict:
    """DALL-E 3 でサムネ画像を生成

    Args:
        prompt: 画像生成プロンプト (英語推奨)
        output_path: 保存先パス
        size: 1024x1024 / 1792x1024 / 1024x1792
        quality: standard ($0.040-0.080) / hd ($0.080-0.120)

    Returns:
        {'success': bool, 'path': str, 'cost_usd': float, 'reason': str}
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"success": False, "path": "", "cost_usd": 0, "reason": "OPENAI_API_KEY未設定"}

    today_count = _count_today()
    if today_count >= DAILY_LIMIT:
        return {
            "success": False,
            "path": "",
            "cost_usd": 0,
            "reason": f"1日の上限{DAILY_LIMIT}件到達",
        }

    # gpt-image-1 公称価格 (medium=標準, high=高品質)
    cost_map = {
        ("1024x1024", "standard"): 0.042,
        ("1024x1024", "hd"): 0.167,
        ("1792x1024", "standard"): 0.063,
        ("1792x1024", "hd"): 0.250,
        ("1024x1792", "standard"): 0.063,
        ("1024x1792", "hd"): 0.250,
    }
    est_cost = cost_map.get((size, quality), 0.063)

    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt[:4000],
            "n": 1,
            "size": _SIZE_MAP.get(size, size),
            "quality": _QUALITY_MAP.get(quality, quality),
            # gpt-image-1 は b64_json のみ。response_format は使わない
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        DALLE_API,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        return {"success": False, "path": "", "cost_usd": 0, "reason": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"success": False, "path": "", "cost_usd": 0, "reason": f"{type(e).__name__}: {e}"}

    if not res.get("data") or not res["data"][0].get("b64_json"):
        return {"success": False, "path": "", "cost_usd": 0, "reason": "レスポンスに b64_json なし"}

    b64 = res["data"][0]["b64_json"]
    revised_prompt = res["data"][0].get("revised_prompt", prompt)[:300]

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    try:
        img_bytes = base64.b64decode(b64)
        with open(output_path, "wb") as f:
            f.write(img_bytes)
    except Exception as e:
        return {"success": False, "path": "", "cost_usd": 0, "reason": f"画像保存失敗: {e}"}

    _log_usage(prompt, est_cost, size, quality)

    return {
        "success": True,
        "path": output_path,
        "cost_usd": est_cost,
        "revised_prompt": revised_prompt,
        "reason": "ok",
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 dalle_thumbnail_gen.py '<prompt>' [output_path]")
        sys.exit(1)
    prompt = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dalle_test.png"
    r = generate_thumbnail(prompt, out, size="1792x1024", quality="standard")
    print(json.dumps(r, ensure_ascii=False, indent=2))
