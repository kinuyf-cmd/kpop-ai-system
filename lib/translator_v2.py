"""translator v2 — Claude Sonnet 4.6 + Prompt caching + Structured outputs

korean_translator.translate_ko_to_ja() のClaude版。OpenAI gpt-4o-mini代替。

機能:
- Claude Sonnet 4.6 (K-pop知識でgpt-4o-miniより精度高)
- Prompt caching: 翻訳ルール+グロッサリー (~1500tokens) をcache → 90%削減
- Structured outputs: 翻訳結果に加えて hangul残存検出/proper noun使用を schema化
- 固有名詞辞書 (config/korean_proper_nouns.json) で前置換は維持

Usage:
    from lib.translator_v2 import translate_ko_to_ja_v2
    r = translate_ko_to_ja_v2(korean_text, context='K-POP entertainment news')
    # r: {'success': bool, 'translated': str, 'residual_hangul_count': int, ...}
"""
from __future__ import annotations
import os
import json
import re
import datetime
from pathlib import Path

import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

# 既存の固有名詞辞書とutil再利用
from lib.korean_translator import apply_proper_noun_dict, _count_today, _update_threshold

LOG = '/home/aiuser/kpop-ai-system/logs/translation_v2.jsonl'
DAILY_LIMIT = 500

# Prompt caching用 翻訳ルール (~1500 tokens)
TRANSLATOR_SYSTEM = """あなたはK-POP専門メディアの韓国語→日本語翻訳者です。以下のガイドラインで自然な日本語に翻訳してください。

【アーティスト名】日本で定着した英語表記を使用
- 뉴진스→NewJeans / 르세라핌→LE SSERAFIM / 아이브→IVE
- 세븐틴→SEVENTEEN / 스트레이키즈→Stray Kids / 에스파→aespa
- 블랙핑크→BLACKPINK / 트와이스→TWICE / 엔하이픈→ENHYPEN
- 방탄소년단/BTS→BTS / 빅뱅→BIGBANG / 투바투→TXT
- 아이들→(G)I-DLE / 일릿→ILLIT / 베이비몬스터→BABYMONSTER
- 라이즈→RIIZE / 보이넥스트도어→BOYNEXTDOOR / 트레저→TREASURE
- 키스오브라이프→KISS OF LIFE / 코르티스→CORTIS
- 1字メンバー名: 진→BTSメンバーはJIN / 뷔→V / 키→KEY / 비→Rain (歌手) / 탑→T.O.P
  ただし「진해성」「진심」「비싸다」等は人名ではないので文脈判断

【専門用語の統一】
- 컴백→カムバック / 음방→音楽番組 / 솔로곡→ソロ曲
- 팬미팅→ファンミーティング / 콘서트→コンサート / 발매→リリース
- 데뷔→デビュー / 활동→活動 / 공식→公式 / 신곡→新曲
- 미니앨범→ミニアルバム / 정규앨범→正規アルバム
- 음원→音源 / 차트→チャート / 1위→1位

【文体ガイドライン】
1. 文末は単調を避け「~した」「~と語った」「~と明かした」「~と発表した」「~と判明した」を文脈で使い分け
2. 「밝혔다」を機械的に「明らかにした」と訳さず、文脈で「述べた」「発表した」「明かした」を選ぶ
3. 「~한 가운데」は「~中、」と簡潔に
4. 直訳的な「~とのこと」「~と伝えられている」を避け、断定的に書く
5. 韓国語独特の比喩は日本語的に意訳
6. 数字・日付・曲名・アルバム名は原文通り維持
7. 「~を引き寄せた」「~を集めた」など過度な韓国語直訳を避ける

【出力ルール】
- 自然で読みやすい日本語のみ
- 説明・注釈・前置き・引用符は不要 (本文のみ)
- アーティスト名は初出時のみ「BTS (방탄소년단)」のように韓国語併記、以降は英語のみ
- 楽曲名: 英語="引用符"、日本語=「鉤括弧」、韓国語=初出時のみ括弧併記
- 文末は連続3文以上同じ語尾を禁止 (です/ます/でした/とのことを分散)
- 年度は半角4桁、順位は半角、序数は英数 (1st/2nd)
- 「いかがでしょうか」「最後に」セクション禁止
- テンプレートラベル (リード文:/導入文:/セクション1:) は出力に含めない

【出力形式】
JSON schemaに従い以下のフィールドを返す:
- translated: 翻訳済みの日本語本文 (本文のみ)
- residual_korean_count: 翻訳後のhangul残存文字数 (グロッサリーで翻訳しきれなかった分)
- proper_nouns_used: 翻訳で使用した重要固有名詞のリスト
"""

_TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "translated": {"type": "string"},
        "residual_korean_count": {"type": "integer"},
        "proper_nouns_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["translated", "residual_korean_count"],
    "additionalProperties": False,
}

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def translate_ko_to_ja_v2(text: str, context: str = 'K-POP entertainment news') -> dict:
    """Claude Sonnet 4.6 で韓国語→日本語翻訳

    Returns:
        {'success': bool, 'translated': str, 'reason': str,
         'residual_korean_count': int, 'proper_nouns_used': [...]}
    """
    if not text or not text.strip():
        return {'success': False, 'translated': '', 'reason': 'empty input'}

    used = _count_today()
    _update_threshold(used)
    if used >= DAILY_LIMIT:
        return {'success': False, 'translated': text, 'reason': f'1日上限{DAILY_LIMIT}到達'}

    # 固有名詞を決定論的に前置換 (既存ロジック再利用)
    text_pre, replaced_count = apply_proper_noun_dict(text)

    user_prompt = (
        f"Context: {context}\n\n"
        f"韓国語原文 (固有名詞は事前に日本語表記済み):\n"
        f"{text_pre[:3000]}\n\n"
        f"上記をJSON schemaに従って自然な日本語に翻訳してください。"
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2500,
            system=[{
                "type": "text",
                "text": TRANSLATOR_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _TRANSLATE_SCHEMA,
                },
            },
            messages=[{"role": "user", "content": user_prompt}],
        )

        text_resp = next((b.text for b in response.content if b.type == 'text'), '{}')
        try:
            result = json.loads(text_resp)
        except json.JSONDecodeError:
            return {'success': False, 'translated': text_pre, 'reason': f'schema parse err: {text_resp[:100]}'}

        translated = result.get('translated', '').strip()
        residual = result.get('residual_korean_count', 0)
        nouns = result.get('proper_nouns_used', [])

        # ログ記録
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        usage = response.usage
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'date': datetime.date.today().isoformat(),
                'ts': datetime.datetime.now().isoformat(),
                'context': context,
                'input_chars': len(text),
                'output_chars': len(translated),
                'pre_replaced': replaced_count,
                'residual_korean_count': residual,
                'usage': {
                    'input': usage.input_tokens,
                    'output': usage.output_tokens,
                    'cache_create': getattr(usage, 'cache_creation_input_tokens', 0),
                    'cache_read': getattr(usage, 'cache_read_input_tokens', 0),
                },
            }, ensure_ascii=False) + '\n')

        # 2026-05-12: 出力に hangul 残存があれば success=False を返す。
        # gate より上流で潰すことで、breaking/event/comeback の `if not success: continue` に
        # 載せて自動 skip させる二段防御。
        from lib.korean_translator import _residue_verdict
        residue = _residue_verdict(translated)
        if residue['verdict'] == 'BLOCK':
            return {
                'success': False,
                'translated': translated,
                'reason': f'hangul_residue: {residue["reason"]}',
                'residual_korean_count': residual,
                'proper_nouns_used': nouns,
                'pre_replaced': replaced_count,
            }

        return {
            'success': True,
            'translated': translated,
            'residual_korean_count': residual,
            'proper_nouns_used': nouns,
            'pre_replaced': replaced_count,
            'reason': '',
        }

    except anthropic.RateLimitError:
        return {'success': False, 'translated': text_pre, 'reason': 'Claude rate limit'}
    except anthropic.APIStatusError as e:
        return {'success': False, 'translated': text_pre, 'reason': f'API err {e.status_code}'}
    except Exception as e:
        return {'success': False, 'translated': text_pre, 'reason': f'err: {type(e).__name__}: {str(e)[:100]}'}


if __name__ == '__main__':
    sample = """블랙핑크의 지수가 2026년 5월 콘서트에서 새로운 솔로 곡을 발표했다.
팬들은 그녀의 컴백을 열렬히 환영했으며, 음원 차트에서 1위를 차지했다고 발표했다.
이번 콘서트는 서울에서 개최되었으며, 약 10만명의 관객이 참여했다."""
    r = translate_ko_to_ja_v2(sample)
    print(json.dumps(r, ensure_ascii=False, indent=2))
