"""K-POP factcheck コーパス生成 (Phase 4)

artist_master.json を Claude factcheck_v2 で参照できる
平文テキスト形式に変換する。Anthropic の document content block で渡し、
cache_control 1h で固定することで:

  - artist の人数 / デビュー年 / メンバー名 / 所属事務所の誤りを web_search に
    頼らず検出できる (Web Search 課金抑制)。
  - cache_read 0.1x で繰り返し参照可能。

注意: factcheck_v2 は structured outputs (output_config.format) を使用しているため
Citations 機能 (citations.enabled=true) は併用不可。citations 無効の document を
「参考資料」として渡すに留める。
"""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
from functools import lru_cache

MASTER_PATH = Path('/home/aiuser/kpop-ai-system/config/artist_master.json')


def _format_member(m: dict) -> str:
    """1メンバー分の1行サマリ"""
    name = m.get('name', '')
    name_ko = m.get('name_ko', '')
    bd = m.get('birthday', '')
    role = m.get('role', '')
    bits = [name]
    if name_ko:
        bits.append(f'({name_ko})')
    if bd:
        bits.append(f'生年月日: {bd}')
    if role:
        bits.append(f'役割: {role}')
    return ' / '.join(bits)


def _format_artist(a: dict) -> str:
    """1アーティスト分のtextブロック生成"""
    lines = []
    name_en = a.get('name_en', '')
    name_ko = a.get('name_ko', '')
    name_ja = a.get('name_ja', '')
    typ = a.get('type', 'group')
    # 2026-07-21: 未検証の agency を「不明」と書かない。corpus は factcheck が
    # 「確定データ」として読むため、裏取りしていない項目は行ごと省略する
    # (「不明」と書くと確定情報の中に無意味な行が混ざる)。
    agency = a.get('agency', '')
    debut = a.get('debut_date', '')

    header = f"## {name_en}"
    if name_ko:
        header += f" ({name_ko})"
    if name_ja and name_ja not in (name_en, name_ko):
        header += f" / {name_ja}"
    lines.append(header)

    lines.append(f"- 種別: {typ}")
    if agency:
        lines.append(f"- 所属事務所: {agency}")
    if debut:
        lines.append(f"- デビュー日: {debut}")

    members = a.get('members', [])
    if members:
        lines.append(f"- メンバー人数: {len(members)}人")
        lines.append("- メンバー:")
        for m in members:
            lines.append(f"  - {_format_member(m)}")

    former = a.get('former_members', [])
    if former:
        lines.append("- 脱退メンバー (現メンバーに含めない):")
        for fm in former:
            if isinstance(fm, dict):
                lines.append(f"  - {fm.get('name', fm)}")
            else:
                lines.append(f"  - {fm}")

    return "\n".join(lines)


@lru_cache(maxsize=1)
def build_corpus() -> str:
    """artist_master.json を text corpus に変換 (LRU cache で 1回のみ生成)"""
    if not MASTER_PATH.exists():
        return ""
    try:
        d = json.loads(MASTER_PATH.read_text(encoding='utf-8'))
    except Exception:
        return ""
    artists = d.get('artists', [])
    if not artists:
        return ""

    body_parts = [
        "# K-POPアーティスト基礎情報コーパス",
        "",
        "以下は K-POP 主要アーティストの確定情報 (デビュー日/所属事務所/メンバー人数/メンバー名)。",
        "factcheck 時はこれを優先参照し、本文中の数値や名前と矛盾があれば critical/high で指摘すること。",
        "ここに記載のないアーティストは web_search ツール等で別途検証。",
        "",
        "---",
    ]
    for a in artists:
        body_parts.append("")
        body_parts.append(_format_artist(a))
    return "\n".join(body_parts)


def corpus_hash() -> str:
    """corpus 内容の hash (将来 Files API へ移行時の change detection 用)"""
    return hashlib.sha256(build_corpus().encode('utf-8')).hexdigest()[:16]


if __name__ == '__main__':
    c = build_corpus()
    print(f"corpus size: {len(c)} chars ({len(c)//2} tokens est)")
    print(f"corpus hash: {corpus_hash()}")
    print("---")
    print(c[:1500])
