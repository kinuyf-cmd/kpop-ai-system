"""Claude Vision pre-publish gate (2026-05-10完璧化)

サムネイル画像が記事のartistを実際に写しているかをClaude Visionで検証。
URL/title照合では分からない「画像内の誰か」を判定する最終防衛層。

使用方法:
    from lib.thumbnail_vision_gate import vision_validate
    ok, reason = vision_validate('/tmp/thumb.jpg', 'BLACKPINK')
    if not ok:
        # blockする
        ...

キャッシュ: 画像のSHA256をキーに結果を保存。同じ画像は再検証しない。
コスト: 1画像あたり約$0.001 (Opus 4.7、画像input)
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

CACHE_PATH = Path('/home/aiuser/kpop-ai-system/data/vision_gate_cache.json')
CACHE_TTL_DAYS = 30
LOG_PATH = Path('/home/aiuser/kpop-ai-system/logs/vision_gate.jsonl')

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _image_hash(image_path: str) -> str:
    """画像内容のSHA256ハッシュ"""
    h = hashlib.sha256()
    with open(image_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    """30日超のエントリを掃除して保存"""
    cutoff = datetime.now().timestamp() - (CACHE_TTL_DAYS * 86400)
    cleaned = {k: v for k, v in cache.items() if v.get('ts', 0) >= cutoff}
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cleaned, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({**entry, 'ts': datetime.now().isoformat()}, ensure_ascii=False) + '\n')
    except OSError:
        pass


def vision_validate(image_path: str, expected_artist: str,
                    article_title: str = '') -> tuple[bool, str]:
    """画像にexpected_artistが写っているかをClaude Visionで判定

    Args:
        image_path: 検証するJPEG/PNG画像パス
        expected_artist: 期待するK-popアーティスト名 (グループ or solo)
        article_title: 記事タイトル (判定文脈の補強用、optional)

    Returns:
        (ok, reason): okがTrueなら合格、Falseなら不合格 + 理由
    """
    if not os.path.exists(image_path):
        return False, f'image not found: {image_path}'
    if not expected_artist:
        return True, 'no expected_artist (skip vision check)'

    cache_key = f"{_image_hash(image_path)}:{expected_artist.lower()}"
    cache = _load_cache()
    if cache_key in cache:
        cached = cache[cache_key]
        return cached['ok'], f"[cached] {cached['reason']}"

    # 画像をbase64エンコード
    ext = os.path.splitext(image_path)[1].lower().lstrip('.')
    media_type = 'image/png' if ext == 'png' else 'image/jpeg'
    with open(image_path, 'rb') as f:
        image_b64 = base64.standard_b64encode(f.read()).decode('utf-8')

    prompt = (
        f"K-pop画像審査。この画像を以下の手順で厳密に判定してください。\n\n"
        "ステップ1: 画像に何が写っているか観察 (人物/動物/物体/イラスト/ロゴ/抽象)\n"
        "ステップ2: 人物が写っている場合、推定できる特徴 (人数/性別/年齢層/服装/背景/ロゴ等)\n"
        f"ステップ3: それが「{expected_artist}」のメンバーと整合するか判定\n\n"
    )
    if article_title:
        prompt += f"参考: 記事タイトル「{article_title}」\n\n"
    prompt += (
        f"判定:\n"
        f"- {expected_artist}本人 or 所属メンバー確実 → YES\n"
        f"- 別アーティスト/抽象アート/関係ない人物 → NO\n"
        "- K-pop知識で特定できない場合は曖昧でNOにせず、画像の見た目だけで判定 (例: 公式ロゴあり=YES寄り、無名スナップ=曖昧でも本人写真ならYES)\n"
        "- 不一致を疑う具体的根拠 (人数違い/明らかに別人) があるときのみNO\n\n"
        "1行のJSONで返答:\n"
        '{"verdict": "YES", "reason": "理由"}'
    )

    try:
        client = _get_client()
        # K-pop識別精度のため Sonnet 4.6 採用 (Haikuはaespa↔TWICE誤認)
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=400,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64',
                                                  'media_type': media_type,
                                                  'data': image_b64}},
                    {'type': 'text', 'text': prompt},
                ],
            }],
        )
        text = next((b.text for b in response.content if b.type == 'text'), '')
        # JSON抽出 (前後のテキストを許容)
        import re as _re
        m = _re.search(r'\{[^{}]*"verdict"[^{}]*\}', text)
        if not m:
            # フォールバック: テキストから YES/NO 推定
            ok = 'YES' in text.upper() and 'NO' not in text.upper()[:20]
            reason = text[:200]
        else:
            try:
                parsed = json.loads(m.group())
                verdict = (parsed.get('verdict') or '').upper()
                ok = verdict == 'YES'
                reason = parsed.get('reason', '')[:200]
            except json.JSONDecodeError:
                ok = 'YES' in text.upper()
                reason = text[:200]

        cache[cache_key] = {
            'ok': ok, 'reason': reason,
            'ts': datetime.now().timestamp(),
            'usage': {'input': response.usage.input_tokens,
                      'output': response.usage.output_tokens},
        }
        _save_cache(cache)
        _log({'image': image_path, 'artist': expected_artist,
              'ok': ok, 'reason': reason,
              'tokens': response.usage.input_tokens + response.usage.output_tokens})
        return ok, reason

    except anthropic.RateLimitError as e:
        _log({'image': image_path, 'artist': expected_artist, 'err': f'rate_limit: {e}'})
        return True, f'vision_skip (rate limit)'  # FAIL OPEN: 過剰BLOCK回避
    except anthropic.APIStatusError as e:
        _log({'image': image_path, 'artist': expected_artist, 'err': f'api_err {e.status_code}'})
        return True, f'vision_skip (API err {e.status_code})'  # FAIL OPEN
    except Exception as e:
        _log({'image': image_path, 'artist': expected_artist, 'err': str(e)[:200]})
        return True, f'vision_skip ({type(e).__name__})'  # FAIL OPEN


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 thumbnail_vision_gate.py <image> <expected_artist> [title]")
        sys.exit(1)
    ok, reason = vision_validate(sys.argv[1], sys.argv[2],
                                  sys.argv[3] if len(sys.argv) > 3 else '')
    print(f"{'✓ PASS' if ok else '✗ FAIL'}: {reason}")
    sys.exit(0 if ok else 1)
