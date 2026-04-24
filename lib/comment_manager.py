#!/usr/bin/env python3
"""
コメント管理・モデレーションシステム v1.0
- WordPressネイティブコメント + 拡張モデレーション
- スパムフィルタ（Akismet連携 + カスタムルール）
- エンゲージメント分析・日次ダイジェスト
- Discord通知連携

Usage:
  python3 lib/comment_manager.py --moderate          # 未承認コメントをモデレート
  python3 lib/comment_manager.py --digest            # 日次ダイジェスト送信
  python3 lib/comment_manager.py --stats             # コメント統計
  python3 lib/comment_manager.py --enable-comments   # WP全記事のコメントを有効化
  python3 lib/comment_manager.py --dry-run --moderate

WordPressコメント設定:
  1. WP管理画面 → 設定 → ディスカッション
     - 「コメントの手動承認を必須にする」: ON
     - 「既承認者のコメントは自動承認」: ON
     - 「名前とメールアドレスの入力を必須にする」: ON
  2. Akismetプラグインを有効化（APIキー設定）
  3. wp-content/themes/your-theme/functions.php に以下を追加:
     - コメントフォームのカスタマイズ（ハニーポット追加）
     - レート制限（1IP/時間あたり10件）
"""
import json
import sys
import os
import re
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "sns_config.json"
COMMENT_LOG = LOGS_DIR / "comment_moderation.jsonl"

JST = timezone(timedelta(hours=9))


# ── 設定 ──

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text()).get("comments", {})
    except Exception:
        return {}


def _wp_auth() -> tuple[str, str]:
    """WordPress REST API認証情報"""
    env_file = BASE_DIR / ".env"
    env = {}
    if env_file.exists():
        for line in env_file.read_text().strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()

    site_url = env.get("SITE_URL", os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo"))

    import base64
    wp_auth_path = Path(os.path.expanduser("~/.wp_auth"))
    if wp_auth_path.exists():
        for line in wp_auth_path.read_text().strip().split("\n"):
            m = re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^\s"]+)"?', line.strip())
            if m:
                auth_val = m.group(1).split(": ", 1)[1] if ": " in m.group(1) else m.group(1)
                return site_url, auth_val

    user = env.get("WP_USER", os.environ.get("WP_USER", ""))
    passwd = env.get("WP_PASS", os.environ.get("WP_PASS", ""))
    token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
    return site_url, f"Basic {token}"


# ── ログ ──

def _log(entry: dict):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(COMMENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── スパム判定 ──

def is_spam(comment: dict, config: dict) -> tuple[bool, str]:
    """カスタムスパムフィルタ"""
    mod = config.get("moderation", {})
    content = comment.get("content", {}).get("rendered", "") or ""
    content_plain = re.sub(r'<[^>]+>', '', content).strip()
    author = comment.get("author_name", "")

    # ブロックワード
    blocked = mod.get("blocked_words", [])
    for word in blocked:
        if word in content_plain or word in author:
            return True, f"ブロックワード: {word}"

    # リンク数制限
    max_links = mod.get("max_links_per_comment", 1)
    link_count = len(re.findall(r'https?://', content_plain))
    if link_count > max_links:
        return True, f"リンク過多: {link_count}件（上限{max_links}）"

    # 最小文字数
    min_len = mod.get("min_comment_length", 5)
    if len(content_plain) < min_len:
        return True, f"文字数不足: {len(content_plain)}文字（最小{min_len}）"

    # 最大文字数
    max_len = mod.get("max_comment_length", 2000)
    if len(content_plain) > max_len:
        return True, f"文字数超過: {len(content_plain)}文字（上限{max_len}）"

    # 繰り返し文字（スパム兆候）
    if re.search(r'(.)\1{9,}', content_plain):
        return True, "繰り返し文字検出"

    # URL比率が高すぎる（本文の50%以上がURL）
    url_chars = sum(len(m) for m in re.findall(r'https?://\S+', content_plain))
    if len(content_plain) > 0 and url_chars / len(content_plain) > 0.5:
        return True, "URL比率過多"

    return False, ""


# ── WordPress API ──

def _wp_api(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    site_url, auth = _wp_auth()
    url = f"{site_url}/wp-json/wp/v2/{endpoint}"

    if data:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method=method)
        req.add_header("Content-Type", "application/json")
    else:
        req = urllib.request.Request(url, method=method)

    req.add_header("Authorization", auth)

    with urllib.request.urlopen(req, timeout=30) as res:
        body = res.read().decode("utf-8")
        return json.loads(body) if body else {}


def fetch_pending_comments() -> list[dict]:
    """未承認コメントを取得"""
    try:
        return _wp_api("comments?status=hold&per_page=50&orderby=date&order=asc")
    except Exception as e:
        print(f"❌ コメント取得失敗: {e}", file=sys.stderr)
        return []


def approve_comment(comment_id: int) -> bool:
    try:
        _wp_api(f"comments/{comment_id}", method="PUT", data={"status": "approved"})
        return True
    except Exception as e:
        print(f"  ❌ 承認失敗 #{comment_id}: {e}", file=sys.stderr)
        return False


def trash_comment(comment_id: int) -> bool:
    try:
        _wp_api(f"comments/{comment_id}", method="DELETE")
        return True
    except Exception as e:
        print(f"  ❌ 削除失敗 #{comment_id}: {e}", file=sys.stderr)
        return False


def spam_comment(comment_id: int) -> bool:
    try:
        _wp_api(f"comments/{comment_id}", method="PUT", data={"status": "spam"})
        return True
    except Exception as e:
        print(f"  ❌ スパム判定失敗 #{comment_id}: {e}", file=sys.stderr)
        return False


# ── モデレーション ──

def moderate_comments(config: dict, dry_run: bool = False) -> dict:
    """未承認コメントを自動モデレート"""
    comments = fetch_pending_comments()
    if not comments:
        print("  未承認コメントはありません")
        return {"total": 0, "approved": 0, "spam": 0, "held": 0}

    stats = {"total": len(comments), "approved": 0, "spam": 0, "held": 0}
    auto_approve = config.get("moderation", {}).get("auto_approve", False)

    for c in comments:
        cid = c.get("id")
        author = c.get("author_name", "匿名")
        content = re.sub(r'<[^>]+>', '', c.get("content", {}).get("rendered", ""))[:80]
        post_id = c.get("post")

        # スパムチェック
        spam, reason = is_spam(c, config)
        if spam:
            print(f"  🚫 SPAM #{cid} by {author}: {reason}")
            if not dry_run:
                spam_comment(cid)
            stats["spam"] += 1
            _log({
                "timestamp": datetime.now(JST).isoformat(),
                "comment_id": cid, "post_id": post_id,
                "author": author, "action": "spam",
                "reason": reason,
            })
            continue

        # 自動承認
        if auto_approve:
            print(f"  ✅ 承認 #{cid} by {author}: {content}")
            if not dry_run:
                approve_comment(cid)
            stats["approved"] += 1
            _log({
                "timestamp": datetime.now(JST).isoformat(),
                "comment_id": cid, "post_id": post_id,
                "author": author, "action": "approved",
            })
        else:
            print(f"  ⏸️ 保留 #{cid} by {author}: {content}")
            stats["held"] += 1
            _log({
                "timestamp": datetime.now(JST).isoformat(),
                "comment_id": cid, "post_id": post_id,
                "author": author, "action": "held",
            })

    return stats


# ── 統計 ──

def get_comment_stats() -> dict:
    """コメント統計を取得"""
    stats = {"approved": 0, "pending": 0, "spam": 0}
    try:
        for status in ["approved", "hold", "spam"]:
            comments = _wp_api(f"comments?status={status}&per_page=1")
            # WP REST APIはヘッダーにX-WP-Total を返すが、urllib では取得困難
            # 代わりにper_page=100で概算
            all_comments = _wp_api(f"comments?status={status}&per_page=100")
            key = "pending" if status == "hold" else status
            stats[key] = len(all_comments) if isinstance(all_comments, list) else 0
    except Exception as e:
        print(f"  ⚠️ 統計取得エラー: {e}", file=sys.stderr)

    return stats


# ── 日次ダイジェスト ──

def build_digest(config: dict) -> str:
    """日次コメントダイジェストを生成"""
    if not COMMENT_LOG.exists():
        return ""

    cutoff = datetime.now(JST) - timedelta(hours=24)
    actions = {"approved": [], "spam": [], "held": []}

    for line in COMMENT_LOG.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=JST)
            if ts >= cutoff:
                action = rec.get("action", "unknown")
                if action in actions:
                    actions[action].append(rec)
        except Exception:
            continue

    total = sum(len(v) for v in actions.values())
    if total == 0:
        return ""

    digest = f"📝 コメントダイジェスト（過去24時間）\n\n"
    digest += f"合計: {total}件\n"
    digest += f"  ✅ 承認: {len(actions['approved'])}件\n"
    digest += f"  🚫 スパム: {len(actions['spam'])}件\n"
    digest += f"  ⏸️ 保留: {len(actions['held'])}件\n"

    if actions["held"]:
        digest += f"\n⏸️ 保留中のコメント（手動確認待ち）:\n"
        for rec in actions["held"][:5]:
            digest += f"  - #{rec.get('comment_id')} by {rec.get('author', '匿名')} (post #{rec.get('post_id')})\n"

    return digest


# ── WordPress functions.php 用スニペット生成 ──

def generate_wp_snippets():
    """WordPressテーマに追加するPHPスニペットを出力"""
    print("""
// ====================================================================
// K-POP Journal コメント機能拡張 — functions.php に追加
// ====================================================================

// 1. ハニーポットフィールド（bot対策）
add_action('comment_form_after_fields', function() {
    echo '<div style="display:none !important;"><label>Leave empty</label>';
    echo '<input type="text" name="kpj_hp_field" value="" tabindex="-1" autocomplete="off"></div>';
});

add_filter('preprocess_comment', function($data) {
    if (!empty($_POST['kpj_hp_field'])) {
        wp_die('スパムと判定されました。');
    }
    return $data;
});

// 2. レート制限（1IP / 時間あたり10件）
add_filter('preprocess_comment', function($data) {
    $ip = $_SERVER['REMOTE_ADDR'];
    $transient_key = 'kpj_comment_rate_' . md5($ip);
    $count = (int) get_transient($transient_key);
    if ($count >= 10) {
        wp_die('コメント投稿の制限に達しました。しばらくしてからお試しください。');
    }
    set_transient($transient_key, $count + 1, HOUR_IN_SECONDS);
    return $data;
}, 1);

// 3. コメント表示のカスタマイズ（リアクション対応準備）
add_filter('comment_text', function($text, $comment) {
    $reactions = get_comment_meta($comment->comment_ID, 'kpj_reactions', true);
    if ($reactions && is_array($reactions)) {
        $html = '<div class="kpj-reactions">';
        $emojis = ['heart' => '❤️', 'fire' => '🔥', 'laugh' => '😂', 'surprise' => '😲'];
        foreach ($reactions as $type => $count) {
            if (isset($emojis[$type]) && $count > 0) {
                $html .= '<span class="kpj-reaction" data-type="' . esc_attr($type) . '">';
                $html .= $emojis[$type] . ' ' . (int)$count . '</span> ';
            }
        }
        $html .= '</div>';
        $text .= $html;
    }
    return $text;
}, 10, 2);

// 4. コメント数をOGPに追加（エンゲージメントシグナル）
add_action('wp_head', function() {
    if (is_single()) {
        $count = get_comments_number();
        if ($count > 0) {
            echo '<meta property="og:comments" content="' . (int)$count . '">' . "\\n";
        }
    }
});

// 5. REST APIでリアクション追加エンドポイント
add_action('rest_api_init', function() {
    register_rest_route('kpopjournal/v1', '/comment-reaction', [
        'methods' => 'POST',
        'callback' => function($request) {
            $comment_id = (int) $request->get_param('comment_id');
            $type = sanitize_text_field($request->get_param('type'));
            $allowed = ['heart', 'fire', 'laugh', 'surprise'];
            if (!in_array($type, $allowed) || !$comment_id) {
                return new WP_Error('invalid', '不正なリクエスト', ['status' => 400]);
            }
            $reactions = get_comment_meta($comment_id, 'kpj_reactions', true) ?: [];
            $reactions[$type] = ($reactions[$type] ?? 0) + 1;
            update_comment_meta($comment_id, 'kpj_reactions', $reactions);
            return ['success' => true, 'reactions' => $reactions];
        },
        'permission_callback' => '__return_true',
    ]);
});

// 6. Webプッシュ購読エンドポイント
add_action('rest_api_init', function() {
    register_rest_route('kpopjournal/v1', '/webpush/subscribe', [
        'methods' => 'POST',
        'callback' => function($request) {
            $sub = $request->get_json_params();
            if (empty($sub['endpoint']) || empty($sub['keys'])) {
                return new WP_Error('invalid', '不正な購読情報', ['status' => 400]);
            }
            // サーバー側の購読リストに追加
            $file = ABSPATH . '../kpop-ai-system/logs/webpush_subscriptions.jsonl';
            file_put_contents($file, json_encode($sub) . "\\n", FILE_APPEND | LOCK_EX);
            return ['success' => true];
        },
        'permission_callback' => '__return_true',
    ]);

    register_rest_route('kpopjournal/v1', '/webpush/unsubscribe', [
        'methods' => 'POST',
        'callback' => function($request) {
            $endpoint = sanitize_text_field($request->get_param('endpoint'));
            if (!$endpoint) {
                return new WP_Error('invalid', '不正なリクエスト', ['status' => 400]);
            }
            $file = ABSPATH . '../kpop-ai-system/logs/webpush_subscriptions.jsonl';
            if (file_exists($file)) {
                $lines = file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
                $filtered = array_filter($lines, function($line) use ($endpoint) {
                    $sub = json_decode($line, true);
                    return ($sub['endpoint'] ?? '') !== $endpoint;
                });
                file_put_contents($file, implode("\\n", $filtered) . "\\n", LOCK_EX);
            }
            return ['success' => true];
        },
        'permission_callback' => '__return_true',
    ]);
});
""")


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="コメント管理 v1.0")
    parser.add_argument("--moderate", action="store_true", help="未承認コメントをモデレート")
    parser.add_argument("--digest", action="store_true", help="日次ダイジェスト")
    parser.add_argument("--stats", action="store_true", help="コメント統計")
    parser.add_argument("--enable-comments", action="store_true", help="全記事のコメント有効化")
    parser.add_argument("--wp-snippets", action="store_true", help="WordPress PHPスニペット出力")
    parser.add_argument("--dry-run", action="store_true", help="変更なしプレビュー")
    args = parser.parse_args()

    config = load_config()

    if args.wp_snippets:
        generate_wp_snippets()
        sys.exit(0)

    if args.stats:
        stats = get_comment_stats()
        print("📊 コメント統計:")
        print(f"  承認済み: {stats['approved']}件")
        print(f"  保留中:   {stats['pending']}件")
        print(f"  スパム:   {stats['spam']}件")
        sys.exit(0)

    if args.digest:
        digest = build_digest(config)
        if digest:
            print(digest)
            # Discord通知連携
            if config.get("notification", {}).get("notify_channel") == "discord":
                try:
                    sys.path.insert(0, str(BASE_DIR))
                    from lib.discord_notifier import send_discord, CHANNEL_WARNING, COLOR_INFO
                    send_discord(
                        CHANNEL_WARNING, "📝 コメントダイジェスト", digest,
                        COLOR_INFO, "comment_digest__daily", "WARNING",
                        dry_run=args.dry_run,
                    )
                except Exception as e:
                    print(f"  ⚠️ Discord通知失敗: {e}", file=sys.stderr)
        else:
            print("  過去24時間のコメントアクティビティはありません")
        sys.exit(0)

    if args.moderate:
        prefix = "[DRY-RUN] " if args.dry_run else ""
        print(f"{prefix}コメントモデレーション開始...")
        stats = moderate_comments(config, dry_run=args.dry_run)
        print(f"\n{prefix}モデレーション結果:")
        print(f"  対象: {stats['total']}件")
        print(f"  承認: {stats['approved']}件")
        print(f"  スパム: {stats['spam']}件")
        print(f"  保留: {stats['held']}件")
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
