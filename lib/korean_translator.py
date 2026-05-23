#!/usr/bin/env python3
"""Korean → Japanese 翻訳 (GPT-4o-mini)

固有名詞は外部辞書 (config/korean_proper_nouns.json) で前置換し、
GPTには日本語/英語表記済みのテキストを渡す。これにより翻訳漏れを根治する。
辞書漏れは lib.translation_residue_check が公開直前に BLOCK する二段防御。
"""
import os, json, re, urllib.request, datetime, functools
from dotenv import load_dotenv
load_dotenv()

API = "https://api.openai.com/v1/chat/completions"
LOG = '/home/aiuser/kpop-ai-system/logs/translation.jsonl'
DAILY_LIMIT = 500
PROPER_NOUNS_PATH = '/home/aiuser/kpop-ai-system/config/korean_proper_nouns.json'


@functools.lru_cache(maxsize=1)
def _load_proper_nouns():
    """固有名詞辞書をロード。長い表記から先にマッチさせるため key 長で降順 sort。"""
    try:
        d = json.load(open(PROPER_NOUNS_PATH, encoding='utf-8'))
    except Exception:
        return []
    pairs = []
    for section in ('groups', 'members', 'labels', 'common_terms', 'shows_and_media', 'personalities'):
        for k, v in (d.get(section) or {}).items():
            if k and v and not k.startswith('_'):
                pairs.append((k, v))
    # 長い key を先にマッチさせる (e.g. "스트레이키즈" を "스트레이"より先に)
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def apply_proper_noun_dict(text: str) -> tuple[str, int]:
    """前置換: 固有名詞辞書で単純な substring 置換。

    Returns: (置換済テキスト, 置換回数)
    """
    if not text:
        return text, 0
    pairs = _load_proper_nouns()
    count = 0
    for ko, ja in pairs:
        if ko in text:
            count += text.count(ko)
            text = text.replace(ko, ja)
    # 重複併記の除去: 韓国語側を置換した結果 "BTS (BTS)" のような冗長表記が出るため整理
    text = re.sub(r'(\S+?)\s*[（(]\s*\1\s*[)）]', r'\1', text)
    return text, count


def _count_today():
    if not os.path.exists(LOG):
        return 0
    today = datetime.date.today().isoformat()
    return sum(1 for line in open(LOG, encoding='utf-8')
               if line.strip() and json.loads(line).get('date') == today)


THRESHOLD_PATH = '/home/aiuser/kpop-ai-system/data/translation_threshold.json'


def _update_threshold(used):
    """使用率閾値でフラグファイル更新"""
    pct = used / DAILY_LIMIT * 100
    if pct >= 90:
        level = 'critical'
    elif pct >= 80:
        level = 'warning'
    elif pct >= 60:
        level = 'info'
    else:
        level = 'normal'
    flag = {
        'level': level,
        'used': used,
        'limit': DAILY_LIMIT,
        'pct': round(pct, 1),
        'updated_at': datetime.datetime.now().isoformat(),
    }
    os.makedirs(os.path.dirname(THRESHOLD_PATH), exist_ok=True)
    with open(THRESHOLD_PATH, 'w', encoding='utf-8') as f:
        json.dump(flag, f, ensure_ascii=False, indent=2)
    if level in ('warning', 'critical'):
        print(f"  [translation] {level.upper()}: {used}/{DAILY_LIMIT} ({pct:.0f}%)")


def translate_ko_to_ja(text, context='K-POP entertainment news'):
    # 2026-05-10: TRANSLATOR_V2=1 で Claude Sonnet 4.6版に切替
    if os.environ.get('TRANSLATOR_V2') == '1':
        try:
            from lib.translator_v2 import translate_ko_to_ja_v2
            return translate_ko_to_ja_v2(text, context=context)
        except Exception as e:
            print(f"  [translation] v2 fallback to v1: {e}")
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return {'success': False, 'translated': text, 'reason': 'OPENAI_API_KEY未設定'}
    used = _count_today()
    _update_threshold(used)
    if used >= DAILY_LIMIT:
        return {'success': False, 'translated': text, 'reason': f'1日上限{DAILY_LIMIT}到達'}

    # 固有名詞を決定論的に前置換 (アーティスト名/メンバー名/事務所名/番組名/共通用語)
    text, _replaced_count = apply_proper_noun_dict(text)

    # Lv2: agent_lessonsから最新教訓を自動注入
    try:
        from lib.agent_learning_loop import inject_lessons_to_prompt
    except ImportError:
        inject_lessons_to_prompt = lambda a, p: p

    system = ("あなたはK-POP専門メディアの韓国語→日本語翻訳者です。以下のガイドラインで自然な日本語に翻訳してください。\n\n"
              "【アーティスト名】日本で定着した英語表記を使用\n"
              "- 뉴진스→NewJeans / 르세라핌→LE SSERAFIM / 아이브→IVE\n"
              "- 세븐틴→SEVENTEEN / 스트레이키즈→Stray Kids / 에스파→aespa\n"
              "- 블랙핑크→BLACKPINK / 트와이스→TWICE / 엔하이픈→ENHYPEN\n"
              "- 방탄소년단/BTS→BTS / 빅뱅→BIGBANG / 투바투→TXT\n"
              "- 아이들→(G)I-DLE / 일릿→ILLIT / 베이비몬스터→BABYMONSTER\n"
              "- 1字メンバー名は文脈で判断: 진→BTSメンバーはJIN / 뷔→V / 키→KEY / 비→Rain (歌手) /\n"
              "  탑→T.O.P (BIGBANG)。だが「진해성」「진심」「비싸다」等の単独hangul語は人名ではない\n\n"
              "【専門用語の統一】\n"
              "- 컴백→カムバック / 음방→音楽番組 / 솔로곡→ソロ曲\n"
              "- 팬미팅→ファンミーティング / 콘서트→コンサート / 발매→リリース\n"
              "- 데뷔→デビュー / 활동→活動 / 공식→公式 / 신곡→新曲\n"
              "- 미니앨범→ミニアルバム / 정규앨범→正規アルバム\n\n"
              "【文体ガイドライン】\n"
              "1. 文末は単調を避け「~した」「~と語った」「~と明かした」「~と発表した」「~と判明した」を文脈で使い分け\n"
              "2. 「밝혔다」を機械的に「明らかにした」と訳さず、文脈で「述べた」「発表した」「明かした」を選ぶ\n"
              "3. 「~한 가운데」は「~中、」と簡潔に\n"
              "4. 直訳的な「~とのこと」「~と伝えられている」を避け、断定的に書く\n"
              "5. 韓国語独特の比喩は日本語的に意訳\n"
              "6. 数字・日付・曲名・アルバム名は原文通り維持\n"
              "7. 「~を引き寄せた」「~を集めた」など過度な韓国語直訳を避ける\n\n"
              "【出力】自然で読みやすい日本語のみ。説明・注釈・前置き・引用符は不要。本文のみ返す。\n\n"
              "【Lv2追加ルール】\n"
              "- アーティスト名は初出時のみ「BTS (방탄소년단)」のように韓国語併記、以降は英語のみ\n"
              "- 楽曲名: 英語=\"引用符\"、日本語=「鉤括弧」、韓国語=初出時のみ括弧併記\n"
              "- 文末は連続3文以上同じ語尾を禁止 (です/ます/でした/とのことを分散)\n"
              "- 年度は半角4桁、順位は半角、序数は英数 (1st/2nd)\n"
              "- 「いかがでしょうか」「最後に」セクション禁止\n"
              "- テンプレートラベル (リード文:/導入文:/セクション1:) は出力に含めない")

    system = inject_lessons_to_prompt('breaking_news_writer', system)

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f"Context: {context}\n\n韓国語原文:\n{text[:3000]}\n\n日本語訳:"}
        ],
        'temperature': 0.3,
        'max_tokens': 2000,
    }).encode()

    req = urllib.request.Request(API, data=body, headers={
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    })

    try:
        r = urllib.request.urlopen(req, timeout=60)
        res = json.loads(r.read())
    except Exception as e:
        return {'success': False, 'translated': text, 'reason': str(e)[:200]}

    translated = res['choices'][0]['message']['content']
    usage = res.get('usage', {})
    cost = usage.get('prompt_tokens', 0) * 0.15 / 1e6 + usage.get('completion_tokens', 0) * 0.60 / 1e6

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'date': datetime.date.today().isoformat(),
            'ts': datetime.datetime.now().isoformat(),
            'cost_usd': cost,
            'tokens': usage,
        }) + '\n')

    # 2026-05-12: 出力にハングル残存があれば success=False を返す。
    # gate でしか BLOCK されない状態だと「ハングル残存 publish 失敗」だけが残り
    # 呼び出し側 (breaking/event/comeback) がリトライ・別ソース試行できないため、
    # translator 層で潰して呼び出し側の `if not success: continue` で skip させる。
    residue = _residue_verdict(translated)
    if residue['verdict'] == 'BLOCK':
        return {'success': False, 'translated': translated, 'cost_usd': cost,
                'reason': f'hangul_residue: {residue["reason"]}'}
    return {'success': True, 'translated': translated, 'cost_usd': cost}


def _residue_verdict(text: str) -> dict:
    """翻訳出力の hangul 残存判定 (translation_residue_check の薄ラッパ)。
    短い text (タイトル想定 <=100字) は1字でもBLOCK / 本文想定 (>100字) は20字以上でBLOCK。
    """
    try:
        from lib.translation_residue_check import count_hangul, _strip_quoted_proper_nouns
    except Exception:
        return {'verdict': 'PASS', 'reason': ''}
    if not text:
        return {'verdict': 'PASS', 'reason': ''}
    stripped = _strip_quoted_proper_nouns(text)
    hangul = count_hangul(stripped)
    if hangul == 0:
        return {'verdict': 'PASS', 'reason': ''}
    # タイトル想定: 短文で1字でもアウト
    if len(text) <= 100 and hangul >= 1:
        return {'verdict': 'BLOCK', 'reason': f'短文(タイトル想定)にハングル{hangul}字残存'}
    # 本文想定: 20字以上で BLOCK (gate と同基準)
    if hangul >= 20:
        return {'verdict': 'BLOCK', 'reason': f'本文にハングル{hangul}字残存'}
    return {'verdict': 'PASS', 'reason': ''}


if __name__ == '__main__':
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "방탄소년단이 새 앨범을 발표했다."
    print(json.dumps(translate_ko_to_ja(text), ensure_ascii=False, indent=2))
