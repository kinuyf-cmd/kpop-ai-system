#!/usr/bin/env python3
"""GA4 metrics_yesterday.json から trending データを抽出し、WP 上の Code Snippets
プラグインの snippet (id=16) の PHP コードに `$ga_pages = [...]` として埋め込んで
PUT 更新する。

WP server からは `/home/aiuser/kpop-ai-system/` ファイルシステムが見えないため、
File を読みに行く方式は使えない。代わりに「データを PHP リテラルとして埋め込む」
push 型同期で実現する。

Usage:
  python3 tools/sync_trending_to_wp_snippet.py [--dry-run]

cron: */15 7-21 * * * cd /home/aiuser/kpop-ai-system && python3 tools/sync_trending_to_wp_snippet.py >> logs/sync_trending.log 2>&1
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
env_file = BASE / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

SITE = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
SNIPPET_ID = int(os.environ.get("KPJ_TRENDING_SNIPPET_ID", "16"))
METRICS_PATH = BASE / "google_metrics" / "metrics_yesterday.json"


def _php_str(s: str) -> str:
    """PHP string literal (single-quoted, シンプルな escape)"""
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def build_snippet_code(ga_pages: list) -> str:
    """PHP コードに $ga_pages = [...] を埋め込む"""
    # ga_pages を path: pageviews などのみに正規化
    cleaned = []
    for item in ga_pages:
        path = (item.get("page") or "").strip()
        if not path or path == "/":
            continue
        pv = int(item.get("pageviews") or 0)
        if pv <= 0:
            continue
        cleaned.append({
            "page": path,
            "pageviews": pv,
            "users": int(item.get("users") or 0),
            "sessions": int(item.get("sessions") or 0),
        })
    cleaned.sort(key=lambda x: -x["pageviews"])
    cleaned = cleaned[:20]

    # PHP リテラル生成
    php_array_items = []
    for c in cleaned:
        php_array_items.append(
            "    [" +
            f"'page' => {_php_str(c['page'])}, " +
            f"'pageviews' => {c['pageviews']}, " +
            f"'users' => {c['users']}, " +
            f"'sessions' => {c['sessions']}" +
            "],"
        )
    php_array = "[\n" + "\n".join(php_array_items) + "\n]"

    # PHP 配列 (cleaned のうち page だけ抽出して PV 降順)
    php_paths_array = "[\n" + "\n".join(
        f"    {_php_str(c['page'])},"
        for c in cleaned
    ) + "\n]"

    code = f"""// KPJ trending GA4 override (auto-synced from Python)
// last sync: {os.environ.get('SYNC_TS', 'unknown')}
// data source: google_metrics/metrics_yesterday.json (top_landing_pages)

/**
 * /kpopjournal/v1/trending を完全 override
 */
add_filter('rest_pre_dispatch', function ($result, $server, $request) {{
    if ($request->get_route() !== '/kpopjournal/v1/trending') {{
        return $result;
    }}

    $cache_key = 'kpj_api_trending_v2_ga4_synced';
    $cached    = get_transient($cache_key);
    if ($cached !== false) {{
        $r = new WP_REST_Response($cached);
        $r->header('X-KPJ-Cache', 'HIT');
        $r->header('X-KPJ-Override', 'ga4-snippet-synced');
        return $r;
    }}

    $ga_pages = {php_array};
    $trending = [];
    $source   = 'comment_count';

    foreach ($ga_pages as $item) {{
        $path = $item['page'] ?? '';
        if (empty($path) || $path === '/') continue;
        $post_id = url_to_postid(home_url($path));
        if (!$post_id) continue;
        $post = get_post($post_id);
        if (!$post || $post->post_status !== 'publish') continue;

        if (function_exists('kpj_api_format_post')) {{
            $entry = kpj_api_format_post($post);
        }} elseif (function_exists('kpj_api_fmt')) {{
            $entry = kpj_api_fmt($post);
        }} else {{
            $entry = [
                'id'    => $post->ID,
                'title' => get_the_title($post),
                'link'  => get_permalink($post),
                'date'  => get_the_date('c', $post),
            ];
        }}
        $entry['ga4'] = [
            'pageviews' => intval($item['pageviews']),
            'users'     => intval($item['users']),
            'sessions'  => intval($item['sessions']),
        ];
        $entry['views'] = intval($item['pageviews']);
        $trending[] = $entry;
        if (count($trending) >= 10) break;
    }}
    if (!empty($trending)) $source = 'ga4';

    if (empty($trending)) {{
        $q = new WP_Query([
            'posts_per_page' => 10,
            'post_status'    => 'publish',
            'orderby'        => 'comment_count',
            'order'          => 'DESC',
            'date_query'     => [['after' => '30 days ago']],
        ]);
        foreach ($q->posts as $p) {{
            $trending[] = [
                'id'    => $p->ID,
                'title' => get_the_title($p->ID),
                'link'  => get_permalink($p->ID),
                'date'  => get_the_date('c', $p->ID),
            ];
        }}
    }}

    $data = [
        'posts'     => $trending,
        'source'    => $source,
        'generated' => current_time('c'),
    ];
    set_transient($cache_key, $data, 15 * MINUTE_IN_SECONDS);

    $r = new WP_REST_Response($data);
    $r->header('X-KPJ-Cache', 'MISS');
    $r->header('X-KPJ-Override', 'ga4-snippet-synced');
    return $r;
}}, 1, 3);

/**
 * /kpopjournal/v1/home の trending field のみ GA4 ベースに置き換え
 * (latest / by_artist / chart は既存のまま温存)
 */
add_filter('rest_request_after_callbacks', function ($response, $handler, $request) {{
    if ($request->get_route() !== '/kpopjournal/v1/home') return $response;
    if (!($response instanceof WP_REST_Response)) return $response;
    $data = $response->get_data();
    if (!is_array($data) || !isset($data['trending'])) return $response;

    $ga_paths = {php_paths_array};
    $ga_trending = [];
    foreach ($ga_paths as $path) {{
        $post_id = url_to_postid(home_url($path));
        if (!$post_id) continue;
        $post = get_post($post_id);
        if (!$post || $post->post_status !== 'publish') continue;
        if (function_exists('kpj_api_fmt')) {{
            $entry = kpj_api_fmt($post);
        }} elseif (function_exists('kpj_api_format_post')) {{
            $entry = kpj_api_format_post($post);
        }} else {{
            $entry = ['id' => $post->ID, 'title' => get_the_title($post),
                      'link' => get_permalink($post), 'date' => get_the_date('c', $post)];
        }}
        $ga_trending[] = $entry;
        if (count($ga_trending) >= 5) break;
    }}
    if (!empty($ga_trending)) {{
        $data['trending'] = $ga_trending;
        $data['trending_source'] = 'ga4-override';
        $response->set_data($data);
        $response->header('X-KPJ-Home-Trending', 'ga4-override');
    }}
    return $response;
}}, 100, 3);

/**
 * sidebar.php の WP_Query(orderby=comment_count, after=2 days ago, posts_per_page=5)
 * を傍受して GA4 ベースの post_id 配列に置き換える
 */
add_action('pre_get_posts', function ($query) {{
    if (is_admin()) return;
    $oa = $query->get('orderby');
    $dq = $query->get('date_query');
    $ppp = (int) $query->get('posts_per_page');
    $after = is_array($dq) && !empty($dq[0]['after']) ? $dq[0]['after'] : '';
    if ($oa === 'comment_count' && $after === '2 days ago' && $ppp === 5) {{
        $ga_paths = {php_paths_array};
        $ga_ids = [];
        foreach ($ga_paths as $path) {{
            $pid = url_to_postid(home_url($path));
            if ($pid && get_post_status($pid) === 'publish') $ga_ids[] = $pid;
            if (count($ga_ids) >= 10) break;
        }}
        if (!empty($ga_ids)) {{
            $query->set('post__in', $ga_ids);
            $query->set('orderby', 'post__in');
            $query->set('date_query', []);
            $query->set('order', 'ASC');
            $query->set('ignore_sticky_posts', true);
        }}
    }}
}}, 999);

// 即時反映のため home の transient を flush
delete_transient('kpj_api_home_v1');
delete_transient('kpj_api_trending_v1');
"""
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not METRICS_PATH.exists():
        print(f"ERROR: {METRICS_PATH} 不在")
        sys.exit(2)
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    ga_pages = metrics.get("ga4", {}).get("top_landing_pages", [])
    if not isinstance(ga_pages, list) or not ga_pages:
        print(f"ERROR: top_landing_pages 空")
        sys.exit(2)
    print(f"GA4 pages: {len(ga_pages)} (date={metrics.get('date')})")

    import datetime
    os.environ["SYNC_TS"] = datetime.datetime.now().isoformat(timespec="seconds")
    code = build_snippet_code(ga_pages)
    print(f"snippet code size: {len(code)} chars")

    if args.dry_run:
        print("--- DRY-RUN: snippet 先頭 1k ---")
        print(code[:1000])
        return 0

    auth = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
    payload = {
        "code": code,
        "active": True,
    }
    req = urllib.request.Request(
        f"{SITE}/wp-json/code-snippets/v1/snippets/{SNIPPET_ID}",
        method="PUT",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        data = json.loads(r.read())
        err = data.get("code_error")
        if err:
            print(f"PUT OK だが code_error: {err[:300]}")
            return 1
        print(f"✅ snippet {SNIPPET_ID} 更新済 active={data.get('active')} size={len(data.get('code',''))}")

        # transient flush は次回呼び出しでキャッシュ MISS になるため任意。
        # 即時反映したければ別 endpoint で delete_transient 必要だが、15分 TTL なので待つ。
        return 0
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP {e.code}: {e.read().decode('utf-8','replace')[:400]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
