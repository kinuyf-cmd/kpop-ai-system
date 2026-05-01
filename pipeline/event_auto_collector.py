#!/usr/bin/env python3
"""イベント自動収集パイプライン — trend_signals.jsonl から events_manual.json へ自動昇格

実行頻度: 毎日 06:30 (cron)
処理フロー:
  1. trend_signals.jsonl から直近48hのイベント系シグナルを抽出
  2. アーティスト名 × イベント種別でグルーピング
  3. 2ソース以上 or 公式発表キーワード含む → 高信頼度
  4. GPT-4o-miniで日付・会場・タイトルを構造化抽出
  5. events_manual.json に重複チェック後マージ
  6. event_calendar_refresh を連鎖実行
"""
import sys, os, json, re, urllib.request
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
load_dotenv('/home/aiuser/kpop-ai-system/.env')

SIGNALS_PATH = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
EVENTS_PATH = '/home/aiuser/kpop-ai-system/config/events_manual.json'
LOG_PATH = '/home/aiuser/kpop-ai-system/logs/event_auto_collector.log'

# イベント検出キーワード (日韓英)
# 注意: 「ツアー」単独は旅行ツアーにもマッチするため複合形のみ許可
EVENT_KW = [
    # 韓国語
    '콘서트', '팬미팅', '투어', '공연', '라이브', '쇼케이스', '페스티벌',
    # 日本語
    'コンサート', 'ファンミ', 'ライブ', '公演', 'フェス',
    'ポップアップ', 'POP-UP', 'KCON', 'ワールドツアー', 'ドームツアー',
    'アリーナツアー', 'ジャパンツアー', 'ファンイベント', '来日', '日本公演',
    # 英語
    'concert', 'tour', 'fanmeeting', 'showcase', 'festival', 'fan meeting',
]

# 旅行・非エンタメシグナルを除外するキーワード（EVENT_KWにマッチしてもこれがあれば除外）
NOT_EVENT_KW = [
    '旅行', '観光', 'グルメ', '料理', 'ホテル', '航空', 'フライト',
    'セール', '割引', 'OFF', 'ドライブ', '車内',
]

# 公式発表キーワード (信頼度判定用)
OFFICIAL_KW = [
    '公式', '決定', '発表', '開催', '確定', '発売', 'チケット',
    '공식', '발표', '확정', '예정',
    'official', 'confirmed', 'announced',
]

# アーティスト名辞書
ARTIST_NAMES = None


def _load_artist_names():
    global ARTIST_NAMES
    if ARTIST_NAMES is not None:
        return ARTIST_NAMES
    acm_path = '/home/aiuser/kpop-ai-system/config/artist_category_map.json'
    try:
        acm = json.load(open(acm_path, encoding='utf-8'))
        ARTIST_NAMES = list(set(k for k in acm.keys() if len(k) >= 2))
    except Exception:
        ARTIST_NAMES = [
            'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'SEVENTEEN', 'TWICE',
            'IVE', 'LE SSERAFIM', 'ILLIT', 'Stray Kids', 'TXT', 'ENHYPEN',
            'ATEEZ', 'ITZY', 'NCT', 'RIIZE', 'EXO', 'TREASURE',
        ]
    return ARTIST_NAMES


def load_event_signals(hours_back=48):
    """trend_signals.jsonlからイベント系シグナルを抽出"""
    if not os.path.exists(SIGNALS_PATH):
        return []
    cutoff = (datetime.now() - timedelta(hours=hours_back)).isoformat()[:19]
    result = []
    with open(SIGNALS_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
                if sig.get('timestamp', '')[:19] < cutoff:
                    continue
                title = sig.get('title', '')
                title_lower = title.lower()
                if any(kw.lower() in title_lower for kw in EVENT_KW):
                    # 旅行・非エンタメシグナルを除外
                    if any(nkw.lower() in title_lower for nkw in NOT_EVENT_KW):
                        continue
                    result.append(sig)
            except Exception:
                pass
    return result


def detect_artist(title):
    """タイトルからアーティスト名を検出"""
    names = _load_artist_names()
    for name in sorted(names, key=len, reverse=True):
        if name.lower() in title.lower():
            return name
    return None


def detect_event_type(title):
    """イベント種別を判定"""
    t = title.lower()
    # 「ツアー」は旅行ツアーにもマッチするため、アーティスト名 or 音楽用語と共起する場合のみ
    if any(kw in t for kw in ['tour', '투어', 'ドーム', 'アリーナ']):
        return 'concert'
    if 'ツアー' in t and any(kw in t for kw in ['ワールド', 'コンサート', 'ライブ', '公演']):
        return 'concert'
    if any(kw in t for kw in ['fanmeeting', 'ファンミ', '팬미팅', 'fan meeting']):
        return 'fanmeeting'
    if any(kw in t for kw in ['popup', 'ポップアップ', 'pop-up']):
        return 'popup'
    if any(kw in t for kw in ['festival', 'フェス', '페스티벌', 'kcon']):
        return 'festival'
    if any(kw in t for kw in ['showcase', 'ショーケース', '쇼케이스']):
        return 'showcase'
    return 'event'


def is_kpop_related(sig):
    """K-POP関連シグナルか判定

    再発防止: '韓国' 単独だと「韓国旅行」「韓国料理」等の非K-POPシグナルが混入する。
    アーティスト名 or K-POP固有キーワード（kcon, kstyle等）のみを許可する。
    """
    title = sig.get('title', '').lower()
    source = sig.get('source', '')
    # 韓国メディアソースは常にK-POP関連
    if source in ('korean_media',):
        return True
    # アーティスト名が含まれていればK-POP関連
    if detect_artist(sig.get('title', '')):
        return True
    # K-POP固有キーワード（'韓国'単独は旅行・料理等の誤検出の原因なので除外）
    kpop_kw = ['k-pop', 'kpop', 'k-beauty', 'k-food',
               'kcon', 'kstyle', 'olive young', 'bt21', 'line friends',
               '韓国アイドル', '韓国ドラマ', '韓流アイドル', '韓流スター']
    if any(kw in title for kw in kpop_kw):
        return True
    return False


def group_signals(signals):
    """アーティスト×イベント種別でグルーピング (K-POP関連のみ)"""
    groups = defaultdict(list)
    for sig in signals:
        if not is_kpop_related(sig):
            continue
        title = sig.get('title', '')
        artist = detect_artist(title) or 'K-POP'
        etype = detect_event_type(title)
        key = f"{artist}_{etype}"
        groups[key].append(sig)
    return groups


def assess_confidence(sigs):
    """信頼度判定: 2ソース以上=high, 公式KW含む=medium, その他=low"""
    sources = set(s.get('source_id', s.get('source', '')) for s in sigs)
    titles = ' '.join(s.get('title', '') for s in sigs)
    has_official = any(kw in titles for kw in OFFICIAL_KW)

    if len(sources) >= 2:
        return 'high'
    if has_official:
        return 'medium'
    return 'low'


def extract_event_details_gpt(sigs):
    """GPT-4o-miniでイベント詳細を構造化抽出"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return None

    titles = '\n'.join(s.get('title', '') for s in sigs[:5])
    prompt = f"""以下のK-POP関連ニュース見出しからイベント情報を構造化抽出してください。

【見出し】
{titles}

【出力形式】JSON のみ (説明不要)
{{"title": "イベント名 (日本語)", "date_start": "YYYY-MM-DD or null", "date_end": "YYYY-MM-DD or null", "venue": "会場名 or null", "city": "都市名 or null", "artist": "アーティスト名"}}

日付が不明な場合はnull。推測禁止。"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
        'max_tokens': 300,
    }).encode()

    try:
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=body,
            headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json',
            },
        )
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        content = r['choices'][0]['message']['content'].strip()
        # JSONを抽出
        m = re.search(r'\{[^}]+\}', content, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        print(f"  GPT抽出エラー: {e}")
    return None


def load_existing_events():
    """既存イベントをロード"""
    try:
        d = json.load(open(EVENTS_PATH, encoding='utf-8'))
        return d.get('events', [])
    except Exception:
        return []


def is_duplicate(new_event, existing_events):
    """重複チェック: タイトル類似 or 同一アーティスト+同一日付"""
    new_title = new_event.get('title', '').lower()
    new_artist = new_event.get('artist', '').lower()
    new_start = new_event.get('date_start', '')

    for e in existing_events:
        title = e.get('title', '').lower()
        # タイトル部分一致
        if new_title and (new_title in title or title in new_title):
            return True
        # 同一アーティスト+同一開始日
        artist = ' '.join(e.get('tags', [])).lower()
        if new_artist and new_artist in artist and new_start and new_start == e.get('date_start', ''):
            return True
    return False


def main():
    print(f"[{datetime.now().isoformat()}] event_auto_collector 開始")

    # 1. シグナル収集
    signals = load_event_signals(hours_back=48)
    print(f"  イベント系シグナル: {len(signals)}件 (48h)")

    if not signals:
        print("  シグナルなし、終了")
        return

    # 2. グルーピング
    groups = group_signals(signals)
    print(f"  グループ数: {len(groups)}")

    # 3. 信頼度判定 + 昇格候補抽出
    existing = load_existing_events()
    new_events = []
    skipped_low = 0
    skipped_dup = 0

    for key, sigs in groups.items():
        confidence = assess_confidence(sigs)
        if confidence == 'low':
            skipped_low += 1
            continue

        # 4. GPTで構造化抽出
        details = extract_event_details_gpt(sigs)
        if not details:
            continue

        # イベントデータ組み立て
        artist = detect_artist(sigs[0].get('title', '')) or details.get('artist', '') or ''

        # 最終K-POPフィルタ: artist_category_mapに登録済みアーティストのみ許可
        known_artists = _load_artist_names()
        artist_match = any(a.lower() == artist.lower() for a in known_artists) if artist else False
        if not artist_match:
            # タイトルにK-POP明示キーワードがない限りスキップ
            all_titles = ' '.join(s.get('title', '') for s in sigs).lower()
            if not any(kw in all_titles for kw in ['k-pop', 'kpop', 'kcon', 'kstyle', '韓流']):
                skipped_low += 1
                continue
        if not artist:
            artist = 'kpop'

        # タイトルが具体的でなければスキップ (「K-POP公演」等の汎用タイトル)
        extracted_title = details.get('title', '')
        if len(extracted_title) < 10 or extracted_title in ('K-POP公演', 'ファンミーティング', 'コンサート', 'ライブ'):
            skipped_low += 1
            continue

        # 非イベント除外: 旅行・グルメ・セール等のK-POPイベントではないタイトルを除外
        reject_kw = ['旅行', 'グルメ', '料理', 'セール', 'OFF', '割引', 'ドライブ',
                     'ホテル', '航空', 'フライト', '観光', '聖地巡礼']
        extracted_lower = extracted_title.lower()
        if any(kw.lower() in extracted_lower for kw in reject_kw):
            print(f"  SKIP(非イベント): {extracted_title}")
            skipped_low += 1
            continue

        event = {
            'id': f"auto_{artist.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}",
            'type': detect_event_type(sigs[0].get('title', '')),
            'title': details.get('title', sigs[0].get('title', '')[:60]),
            'date_start': details.get('date_start') or '',
            'date_end': details.get('date_end') or details.get('date_start') or '',
            'venue': details.get('venue') or '',
            'city': details.get('city') or '',
            'priority': 'A' if confidence == 'high' else 'B',
            'tags': [artist] if artist else [],
            'auto_collected': True,
            'confidence': confidence,
            'source_count': len(set(s.get('source', '') for s in sigs)),
            'collected_at': datetime.now().isoformat(),
        }

        # 5. 重複チェック
        if is_duplicate(event, existing + new_events):
            skipped_dup += 1
            continue

        new_events.append(event)
        print(f"  ★ 新規: {event['title']} ({confidence}, {event['source_count']}ソース)")

    # 6. events_manual.jsonにマージ
    if new_events:
        existing.extend(new_events)
        data = {
            'events': existing,
            'updated_at': datetime.now().isoformat(),
            'note': 'AI生成(confidence=medium)と手動(confidence=high)の混在。auto_event_articleはhighのみ優先参照',
        }
        with open(EVENTS_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n  events_manual.json 更新: +{len(new_events)}件 (計{len(existing)}件)")

        # 7. event_calendar_refresh を連鎖実行
        try:
            from pipeline.event_calendar_refresh import main as refresh
            refresh()
            print("  event_calendar_refresh 連鎖実行完了")
        except Exception as e:
            print(f"  calendar refresh err: {e}")
    else:
        print(f"\n  新規イベントなし (low={skipped_low}, dup={skipped_dup})")

    print(f"[{datetime.now().isoformat()}] event_auto_collector 完了")


if __name__ == '__main__':
    main()
