#!/usr/bin/env python3
"""
artist_profile_inserter.py - Track D 記事構造ナタリー化
記事テキストからアーティスト名を検出し、プロフィールボックスHTMLを生成・挿入する。
"""

import argparse
import json
import os
import re
import sys

# artist_database.json のパス
_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "artist_database.json")


def _load_database() -> dict:
    """アーティストデータベースを読み込む。"""
    db_path = os.path.normpath(_DB_PATH)
    with open(db_path, "r", encoding="utf-8") as f:
        return json.load(f)


def detect_artist_in_text(text: str) -> list[str]:
    """
    テキスト中に含まれるアーティスト名を検出する。
    config/artist_database.json のキーを照合。
    長い名前から先にマッチさせ、重複を防ぐ。
    """
    db = _load_database()
    # Sort by length descending to match longer names first (e.g. "Stray Kids" before "IVE")
    artist_names = sorted(db.keys(), key=len, reverse=True)

    found: list[str] = []
    for name in artist_names:
        # Escape special regex chars in artist name (e.g. "(G)I-DLE")
        pattern = re.escape(name)
        if re.search(pattern, text, re.IGNORECASE):
            found.append(name)

    return found


def generate_profile_html(artist_name: str) -> str:
    """
    アーティスト名からプロフィールボックスHTMLを生成する。
    """
    db = _load_database()
    if artist_name not in db:
        return ""

    info = db[artist_name]
    members_str = ", ".join(info.get("members", []))
    songs_str = " / ".join(info.get("representative_songs", []))

    html = (
        '<div class="kpj-artist-profile">\n'
        f"  <h3>{artist_name} プロフィール</h3>\n"
        "  <dl>\n"
        f"    <dt>デビュー日</dt><dd>{info.get('debut_date', '不明')}</dd>\n"
        f"    <dt>所属事務所</dt><dd>{info.get('agency', '不明')}</dd>\n"
        f"    <dt>メンバー</dt><dd>{members_str}</dd>\n"
        f"    <dt>代表曲</dt><dd>{songs_str}</dd>\n"
        "  </dl>\n"
        "</div>"
    )
    return html


def insert_profile_into_html(html: str, profile_html: str) -> str:
    """
    プロフィールHTMLを記事HTMLに挿入する。
    </article> の直前に挿入。なければ末尾に追加。
    """
    if not profile_html:
        return html

    # Try to insert before </article>
    article_end = html.rfind("</article>")
    if article_end != -1:
        return html[:article_end] + "\n" + profile_html + "\n" + html[article_end:]

    # Fallback: append at end
    return html + "\n" + profile_html


def main():
    parser = argparse.ArgumentParser(description="記事テキストからアーティストを検出しプロフィールHTMLを生成する")
    parser.add_argument("--text", type=str, help="検索対象テキスト")
    parser.add_argument("--file", type=str, help="記事JSONファイルパス")
    parser.add_argument("--insert-into", type=str, help="プロフィールを挿入するHTMLファイルパス")
    args = parser.parse_args()

    if not args.text and not args.file:
        parser.print_help()
        sys.exit(1)

    text = ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            data = json.load(f)
            text = data.get("content", data.get("html", data.get("title", "")))
    elif args.text:
        text = args.text

    if not text:
        print("ERROR: テキストが空です", file=sys.stderr)
        sys.exit(1)

    artists = detect_artist_in_text(text)
    if not artists:
        print("アーティスト検出: なし")
        sys.exit(0)

    print(f"検出アーティスト: {', '.join(artists)}")
    print()

    for artist in artists:
        profile = generate_profile_html(artist)
        if profile:
            print(profile)
            print()

    # If --insert-into is given, insert profiles into the HTML file
    if args.insert_into:
        with open(args.insert_into, "r", encoding="utf-8") as f:
            html = f.read()
        for artist in artists:
            profile = generate_profile_html(artist)
            if profile:
                html = insert_profile_into_html(html, profile)
        with open(args.insert_into, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"プロフィールを {args.insert_into} に挿入しました")


if __name__ == "__main__":
    main()
