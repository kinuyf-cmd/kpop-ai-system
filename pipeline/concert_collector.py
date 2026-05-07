#!/usr/bin/env python3
"""
コンサート/ライブ情報 自動収集パイプライン

ソース: wowKorea イベント一覧 (https://www.wowkorea.jp/guide/event/)
実行頻度: 毎日 7:30 (cron)

処理フロー:
  1. wowKorea イベント一覧ページをスクレイプ
  2. 各イベントの日程・アーティスト・会場を抽出
  3. events_manual.json に重複チェック後マージ
  4. event_calendar_refresh を連鎖実行
"""
import sys, os, json, re, urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
load_dotenv('/home/aiuser/kpop-ai-system/.env')

EVENTS_PATH = '/home/aiuser/kpop-ai-system/config/events_manual.json'
LOG_PATH = '/home/aiuser/kpop-ai-system/logs/concert_collector.log'
SOURCE_URL = 'https://www.wowkorea.jp/guide/event/'


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def fetch_wowkorea_events():
    """wowKorea イベント一覧をスクレイプ"""
    try:
        req = urllib.request.Request(SOURCE_URL, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; KpopJournalBot/1.0)',
            'Accept-Language': 'ja',
        })
        html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='replace')
    except Exception as e:
        log(f"  wowKorea取得失敗: {e}")
        return []

    events = []

    # パターン: 各イベントブロックを抽出
    # wowKoreaのイベント一覧はシンプルなHTML構造
    # <a href="/guide/event/read/1/XXXXX.html">タイトル</a>
    # 日時：YYYY/MM/DD(曜)～ YYYY/MM/DD(曜)
    # 出演：アーティスト名

    blocks = re.split(r'<hr\s*/?>', html)

    for block in blocks:
        # リンクとタイトル
        link_m = re.search(r'<a[^>]+href="(/guide/event/read/\d+/\d+\.html)"[^>]*>([^<]+)</a>', block)
        if not link_m:
            continue

        url_path = link_m.group(1)
        title = link_m.group(2).strip()
        title = re.sub(r'&amp;', '&', title)
        title = re.sub(r'&#\d+;', '', title)

        # 日程
        date_m = re.search(r'日時[：:]?\s*(\d{4})/(\d{2})/(\d{2})', block)
        date_start = ''
        date_end = ''
        if date_m:
            date_start = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"
            # 終了日
            end_m = re.search(r'[～~]\s*(\d{4})/(\d{2})/(\d{2})', block)
            if end_m:
                date_end = f"{end_m.group(1)}-{end_m.group(2)}-{end_m.group(3)}"
            else:
                date_end = date_start

        # アーティスト
        artist_m = re.search(r'出演[：:]?\s*([^<\n]+)', block)
        artist = artist_m.group(1).strip() if artist_m else ''

        # 会場
        venue_m = re.search(r'会場[：:]?\s*([^<\n]+)', block)
        venue = venue_m.group(1).strip() if venue_m else ''

        # イベント種別判定
        event_type = _detect_type(title)

        events.append({
            'title': title,
            'date_start': date_start,
            'date_end': date_end,
            'venue': venue,
            'artist': artist,
            'type': event_type,
            'source_url': f"https://www.wowkorea.jp{url_path}",
        })

    return events


def _detect_type(title):
    """イベント種別を判定"""
    t = title.lower()
    if any(kw in t for kw in ['tour', 'ツアー', 'concert', 'コンサート', 'live', 'ライブ',
                                'ドーム', 'アリーナ', '公演']):
        return 'concert'
    if any(kw in t for kw in ['fanmeeting', 'ファンミ', 'fan-con', 'ファンコン', 'fanconcert']):
        return 'concert'  # ファンミもコンサートカテゴリに統合
    if any(kw in t for kw in ['popup', 'ポップアップ', 'pop-up']):
        return 'popup'
    if any(kw in t for kw in ['festival', 'フェス', 'kcon', 'awards', 'asea', 'mama']):
        return 'festival'
    if any(kw in t for kw in ['comeback', 'カムバック', 'アルバム']):
        return 'comeback'
    return 'event'


def load_existing():
    try:
        with open(EVENTS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'events': [], 'updated_at': '', 'note': ''}


def is_duplicate(new_ev, existing_events):
    """重複チェック: タイトル部分一致"""
    new_title = new_ev['title'].lower()
    for e in existing_events:
        existing_title = e.get('title', '').lower()
        # 部分一致 (短い方が長い方に含まれる)
        if len(new_title) > 10 and len(existing_title) > 10:
            if new_title[:20] in existing_title or existing_title[:20] in new_title:
                return True
        # 完全一致
        if new_title == existing_title:
            return True
    return False


def _send_alert(title, body, severity="WARNING"):
    """Discord通知"""
    try:
        from lib.discord_channel_router import send_to_channel, ChannelType
        send_to_channel(ChannelType.ALERT, title, body, severity=severity)
    except Exception as e:
        log(f"  Discord通知失敗: {e}")


def main():
    log("=== concert_collector 開始 ===")

    # 1. wowKoreaからイベント取得
    raw_events = fetch_wowkorea_events()
    log(f"  wowKorea取得: {raw_events and len(raw_events) or 0}件")

    if not raw_events:
        log("  イベントなし（ソース障害の可能性）")
        _send_alert(
            "concert_collector 異常",
            "wowKoreaからイベント0件取得。ソースページ変更またはネットワーク障害の可能性。\n手動確認: https://www.wowkorea.jp/guide/event/",
            severity="WARNING"
        )
        return

    # 2. 既存データとマージ
    data = load_existing()
    existing = data.get('events', [])
    today = datetime.now().strftime('%Y-%m-%d')

    added = 0
    skipped = 0
    for ev in raw_events:
        # 終了済みイベントはスキップ
        end_date = ev.get('date_end') or ev.get('date_start', '')
        if end_date and end_date < today:
            skipped += 1
            continue

        # 日程不明はスキップ
        if not ev.get('date_start'):
            skipped += 1
            continue

        # 重複チェック
        if is_duplicate(ev, existing):
            skipped += 1
            continue

        # アーティスト名からタグ生成
        artist = ev.get('artist', '')
        tags = [a.strip() for a in re.split(r'[、,/]', artist) if a.strip()][:5]

        new_event = {
            'id': f"wow_{re.sub(r'[^a-z0-9]', '', ev['title'].lower()[:20])}_{ev['date_start'].replace('-', '')}",
            'type': ev['type'],
            'title': ev['title'],
            'date_start': ev['date_start'],
            'date_end': ev['date_end'],
            'venue': ev['venue'],
            'city': '',
            'priority': 'A',
            'tags': tags,
            'auto_collected': True,
            'confidence': 'high',
            'source': 'wowkorea',
            'source_url': ev.get('source_url', ''),
            'collected_at': datetime.now().isoformat(),
        }

        existing.append(new_event)
        added += 1

    log(f"  追加: {added}件, スキップ: {skipped}件")

    if added > 0:
        data['events'] = existing
        data['updated_at'] = datetime.now().isoformat()

        with open(EVENTS_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        log(f"  events_manual.json 更新: 計{len(existing)}件")

        # カレンダー更新を連鎖実行
        try:
            from pipeline.event_calendar_refresh import main as refresh
            refresh()
            log("  event_calendar_refresh 連鎖実行完了")
        except Exception as e:
            log(f"  calendar refresh err: {e}")
    else:
        log("  新規追加なし")

    # 健全性チェック
    _health_check(data.get('events', existing))

    log("=== concert_collector 完了 ===")


def _health_check(events):
    """カレンダーデータの健全性チェック"""
    today = datetime.now()
    issues = []

    # 1. 未来のコンサートが最低10件あるか
    future_concerts = [e for e in events
                       if e.get('type') in ('concert', 'festival')
                       and e.get('date_start', '') >= today.strftime('%Y-%m-%d')]
    if len(future_concerts) < 10:
        issues.append(f"未来のコンサート/フェスが{len(future_concerts)}件しかない（最低10件必要）")

    # 2. 直近30日にイベントが5件以上あるか
    in30 = (today + timedelta(days=30)).strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')
    near_events = [e for e in events
                   if e.get('date_start', '') >= today_str
                   and e.get('date_start', '') <= in30]
    if len(near_events) < 5:
        issues.append(f"直近30日のイベントが{len(near_events)}件しかない（最低5件必要）")

    # 3. events_manual.json の最終更新が48時間以内か
    try:
        data = json.load(open(EVENTS_PATH, encoding='utf-8'))
        updated = data.get('updated_at', '')
        if updated:
            last = datetime.fromisoformat(updated.replace('Z', '+00:00').split('+')[0])
            hours_ago = (today - last).total_seconds() / 3600
            if hours_ago > 48:
                issues.append(f"events_manual.json最終更新が{hours_ago:.0f}時間前（48時間超過）")
    except:
        issues.append("events_manual.json読み込み失敗")

    # 4. 日程が空のイベントが多すぎないか
    no_date = [e for e in events if not e.get('date_start')]
    if len(no_date) > len(events) * 0.3:
        issues.append(f"日程未定イベントが{len(no_date)}/{len(events)}件（30%超過）")

    if issues:
        body = "**カレンダーデータ健全性チェック NG**\n" + '\n'.join(f"- {i}" for i in issues)
        log(f"  健全性チェック NG: {len(issues)}件")
        for i in issues:
            log(f"    - {i}")
        _send_alert("カレンダー健全性チェック", body, severity="WARNING")
    else:
        log(f"  健全性チェック OK (未来コンサート={len(future_concerts)}, 30日内={len(near_events)})")


if __name__ == '__main__':
    main()
