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

    # Prompt cachingで K-pop審査基準のprefixをcache。同じ判定基準を毎回送らず90%コスト削減
    # 巨大prefix (1024+ tokens) を最初のtext blockに置き、cache_control で固定
    K_POP_AUDIT_PREFIX = (
        "あなたはK-popに精通した画像審査AIです。以下の規則で画像を判定してください。\n\n"
        "## 主要K-popグループ覚え書き\n"
        "- BLACKPINK (YG, 4人, 女性): Jisoo/Jennie/Rosé/Lisa\n"
        "- aespa (SM, 4人, 女性): Karina/Giselle/Winter/Ningning — SMTOWN OFFICIAL\n"
        "- BTS (HYBE/Bighit, 7人, 男性): RM/Jin/Suga/J-Hope/Jimin/V/Jungkook\n"
        "- TWICE (JYP, 9人, 女性): Nayeon/Jeongyeon/Momo/Sana/Jihyo/Mina/Dahyun/Chaeyoung/Tzuyu\n"
        "- NewJeans (ADOR/HYBE, 5人, 女性): Minji/Hanni/Danielle/Haerin/Hyein\n"
        "- IVE (Starship, 6人, 女性): Yujin/Gaeul/Rei/Wonyoung/Liz/Leeseo\n"
        "- LE SSERAFIM (Source/HYBE, 5人, 女性): Sakura/Chaewon/Yunjin/Kazuha/Eunchae\n"
        "- ITZY (JYP, 5人, 女性): Yeji/Lia/Ryujin/Chaeryeong/Yuna\n"
        "- SEVENTEEN (Pledis/HYBE, 13人, 男性)\n"
        "- Stray Kids (JYP, 8人, 男性)\n"
        "- ENHYPEN (Belift/HYBE, 7人, 男性)\n"
        "- TXT/TOMORROW X TOGETHER (Bighit, 5人, 男性)\n"
        "- ATEEZ (KQ, 8人, 男性)\n"
        "- TREASURE (YG, 10人, 男性)\n"
        "- NMIXX (JYP, 6人, 女性)\n"
        "- ILLIT (Belift/HYBE, 5人, 女性)\n"
        "- BABYMONSTER (YG, 7人, 女性)\n"
        "- BOYNEXTDOOR (KOZ/HYBE, 6人, 男性)\n"
        "- RIIZE (SM, 7人, 男性)\n"
        "- TWS (Pledis/HYBE, 6人, 男性)\n"
        "- KISS OF LIFE (S2, 4人, 女性)\n\n"
        "## 判定手順\n"
        "ステップ1: 画像に何が写っているか観察 (人物/動物/物体/イラスト/ロゴ/抽象)\n"
        "ステップ2: 画像内の人物を **必ず指差し数える** (左から1人ずつ)。\n"
        "         この数を people_count に正確に出力。期待アーティスト人数に合わせて\n"
        "         数を fudge してはならない (priming bias 回避)。\n"
        "ステップ3: 人物の特徴 (性別/年齢層/服装/背景/公式ロゴ)\n"
        "ステップ4: 期待アーティストと整合するか判定 (人数差を最重要視)\n\n"
        "## 判定ルール\n"
        "- 期待アーティスト本人 or 所属メンバー確実 → YES\n"
        "- 別アーティスト/抽象アート/関係ない人物 → NO\n"
        "- 公式ロゴ (SMTOWN, YG OFFICIAL, ADOR, JYP等) で所属事務所が確認できる場合は重要な手がかり\n"
        "  例: SMTOWN ロゴ → SM所属artist (aespa/Red Velvet/NCT等) でなければ NO\n"
        "  例: YG OFFICIAL → YG所属 (BLACKPINK/TREASURE/BABYMONSTER等) でなければ NO\n"
        "- 人数差は最厳格チェック: 期待アーティスト人数と people_count の差が ±2 を超えれば NO\n"
        "  (例: BABYMONSTER 7人組 → people_count=6 は -1 で borderline、=5 以下なら NO)\n"
        "  promotional photo で 1人欠ける subset は許容、3人以上欠けるなら別アーティスト疑い\n"
        "- 性別不一致は決定的 → NO\n"
        "- K-pop知識で特定できない曖昧な画像は、見た目で判断 (公式ロゴあり=寄りYES)\n\n"
        "## 出力形式\n"
        '必ず以下のJSON1行で返答 (前後のテキストなし):\n'
        '{"people_count": <integer>, "verdict": "YES" or "NO", "reason": "判定理由 (200字以内、まず people_count とその根拠を述べる)"}\n'
    )
    prompt_specific = (
        f"\n## 今回の判定タスク\n"
        f"期待アーティスト: 「{expected_artist}」\n"
    )
    if article_title:
        prompt_specific += f"記事タイトル: 「{article_title}」\n"
    prompt_specific += "\n上記K-pop覚え書きと判定ルールに従って、画像が「{expected_artist}」を写しているか判定してください。".format(expected_artist=expected_artist)

    try:
        client = _get_client()
        # K-pop識別精度のため Sonnet 4.6 採用 (Haikuはaespa↔TWICE誤認)
        # 2026-05-10: structured outputs (output_config.format) で JSON schema 強制
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=400,
            system=[{
                "type": "text",
                "text": K_POP_AUDIT_PREFIX,
                "cache_control": {"type": "ephemeral"},
            }],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "people_count": {"type": "integer"},
                            "verdict": {"type": "string", "enum": ["YES", "NO"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["people_count", "verdict", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64',
                                                  'media_type': media_type,
                                                  'data': image_b64}},
                    {'type': 'text', 'text': prompt_specific},
                ],
            }],
        )
        # output_config.format で1個目のtext blockに valid JSON が保証される
        text = next((b.text for b in response.content if b.type == 'text'), '{}')
        try:
            parsed = json.loads(text)
            verdict = (parsed.get('verdict') or '').upper()
            ok = verdict == 'YES'
            people_count = parsed.get('people_count')
            reason = parsed.get('reason', '')[:200]
            if people_count is not None:
                reason = f'count={people_count} | {reason}'
        except json.JSONDecodeError:
            ok = False
            reason = f'schema parse err: {text[:100]}'

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
