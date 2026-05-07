#!/usr/bin/env python3
"""smart_thumbnail_selector.py — 記事テーマに合ったサムネイル選択

記事タイトルを分析して:
  - グループ記事 → グループの公式画像
  - ソロ記事 → ソロメンバーの画像
  - 2人記事 → 2人の画像を左右分割合成
  - 抽象記事(ランキング/ガイド) → DALL-Eテーマ画像

Usage:
  from lib.smart_thumbnail_selector import select_thumbnail
  result = select_thumbnail(title, body, post_id)
  # result = {'path': '/tmp/...', 'source': 'wikimedia', ...}
"""
import sys
import os
import re

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

# Known groups and members
GROUPS = {
    'BTS': ['RM', 'JIN', 'SUGA', 'J-HOPE', 'JIMIN', 'V', 'JUNGKOOK', 'ジョングク', 'テテ', 'ジミン'],
    'BLACKPINK': ['JISOO', 'JENNIE', 'ROSE', 'LISA', 'ジス', 'ジェニ', 'ロゼ', 'リサ'],
    'TWICE': ['NAYEON', 'JEONGYEON', 'MOMO', 'SANA', 'JIHYO', 'MINA', 'DAHYUN', 'CHAEYOUNG', 'TZUYU', 'サナ', 'モモ', 'ナヨン'],
    'aespa': ['KARINA', 'GISELLE', 'WINTER', 'NINGNING', 'カリナ', 'ジゼル', 'ウィンター', 'ニンニン'],
    'NewJeans': ['MINJI', 'HANNI', 'DANIELLE', 'HAERIN', 'HYEIN', 'ミンジ', 'ハニ', 'ダニエル', 'ヘリン', 'ヘイン'],
    'IVE': ['YUJIN', 'GAEUL', 'REI', 'WONYOUNG', 'LIZ', 'LEESEO', 'ウォニョン', 'レイ', 'ユジン'],
    'LE SSERAFIM': ['SAKURA', 'CHAEWON', 'YUNJIN', 'KAZUHA', 'EUNCHAE', 'サクラ', 'カズハ', 'ユンジン'],
    'Stray Kids': ['BANG CHAN', 'LEE KNOW', 'CHANGBIN', 'HYUNJIN', 'HAN', 'FELIX', 'SEUNGMIN', 'I.N', 'ヒョンジン', 'フィリックス'],
    'SEVENTEEN': ['S.COUPS', 'JEONGHAN', 'JOSHUA', 'JUN', 'HOSHI', 'WONWOO', 'WOOZI', 'THE8', 'MINGYU', 'DK', 'SEUNGKWAN', 'VERNON', 'DINO'],
    'ENHYPEN': ['JUNGWON', 'HEESEUNG', 'JAY', 'JAKE', 'SUNGHOON', 'SUNOO', 'NI-KI'],
    'TXT': ['YEONJUN', 'SOOBIN', 'BEOMGYU', 'TAEHYUN', 'HUENINGKAI', 'ヨンジュン', 'スビン'],
    'EXO': ['XIUMIN', 'SUHO', 'BAEKHYUN', 'CHEN', 'CHANYEOL', 'D.O.', 'KAI', 'SEHUN'],
    'NCT': ['TAEYONG', 'MARK', 'JAEHYUN', 'DOYOUNG', 'HAECHAN'],
    'ITZY': ['YEJI', 'LIA', 'RYUJIN', 'CHAERYEONG', 'YUNA', 'リュジン'],
    'NMIXX': ['LILY', 'HAEWON', 'SULLYOON', 'BAE', 'JIWOO', 'KYUJIN'],
    'BABYMONSTER': ['RUKA', 'PHARITA', 'ASA', 'AHYEON', 'RAMI', 'CHIQUITA', 'HARAM'],
    'BIGBANG': ['G-DRAGON', 'T.O.P', 'TAEYANG', 'DAESUNG'],
    'NCT WISH': [],
    'RIIZE': [],
}

# Map member → group
MEMBER_TO_GROUP = {}
for group, members in GROUPS.items():
    for member in members:
        MEMBER_TO_GROUP[member.upper()] = group


def analyze_article_subjects(title, body=''):
    """記事タイトルから主題を分析

    Returns:
        {
            'type': 'group' | 'solo' | 'duo' | 'multi_group' | 'abstract',
            'subjects': ['BTS'] or ['JIMIN'] or ['G-DRAGON', 'KARINA'],
            'groups': ['BTS'] or ['BIGBANG', 'aespa'],
        }
    """
    text = title.upper()
    body_upper = (body[:500] if body else '').upper()

    found_groups = []
    found_members = []

    # グループ名検出 (長い名前を先にチェック → "NCT WISH"が"NCT"より先にマッチ)
    matched_spans = set()
    for group in sorted(GROUPS.keys(), key=len, reverse=True):
        gu = group.upper()
        idx = text.find(gu)
        if idx >= 0:
            span = (idx, idx + len(gu))
            # 既にマッチした範囲内なら重複スキップ (NCT WISH→NCT)
            if any(s <= idx < e for s, e in matched_spans):
                continue
            matched_spans.add(span)
            found_groups.append(group)

    # メンバー名検出
    for member, group in MEMBER_TO_GROUP.items():
        if member in text:
            found_members.append((member, group))

    # 判定
    if len(found_groups) >= 2:
        # 2グループ以上 → duo or multi_group
        return {
            'type': 'duo' if len(found_groups) == 2 else 'multi_group',
            'subjects': found_groups[:2],
            'groups': found_groups[:2],
        }

    if len(found_members) >= 2:
        # 2メンバー以上 (異なるグループの場合)
        groups_of_members = list(set(g for _, g in found_members))
        if len(groups_of_members) >= 2:
            members_list = [m for m, _ in found_members[:2]]
            return {
                'type': 'duo',
                'subjects': members_list,
                'groups': groups_of_members[:2],
            }

    if found_members:
        member, group = found_members[0]
        # ソロ記事かグループ記事かをタイトルで判定
        # 「BTSのV」→ソロ、「BTS」だけ→グループ
        return {
            'type': 'solo',
            'subjects': [member],
            'groups': [group],
        }

    if found_groups:
        return {
            'type': 'group',
            'subjects': [found_groups[0]],
            'groups': [found_groups[0]],
        }

    return {
        'type': 'abstract',
        'subjects': [],
        'groups': [],
    }


def _resolve_image(name, post_id=''):
    """1人分の画像を解決"""
    try:
        from lib.thumbnail_source_resolver import resolve
        result = resolve(name, post_id=post_id, article_type='concrete')
        if result and result.get('image_path') and os.path.exists(result['image_path']):
            return result
    except Exception:
        pass
    return None


def _composite_duo(img_path1, img_path2, output_path):
    """2枚の画像を左右に分割合成して1200x675に"""
    try:
        from PIL import Image
        im1 = Image.open(img_path1).convert('RGB')
        im2 = Image.open(img_path2).convert('RGB')

        W, H = 1200, 675
        half_w = W // 2

        # 各画像をhalf_w x Hにリサイズ+クロップ
        for im, side_w in [(im1, half_w), (im2, half_w)]:
            pass

        def crop_center(im, tw, th):
            iw, ih = im.size
            scale = max(tw / iw, th / ih)
            im = im.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
            niw, nih = im.size
            left = (niw - tw) // 2
            top = (nih - th) // 2
            return im.crop((left, top, left + tw, top + th))

        left_img = crop_center(im1, half_w, H)
        right_img = crop_center(im2, half_w, H)

        canvas = Image.new('RGB', (W, H))
        canvas.paste(left_img, (0, 0))
        canvas.paste(right_img, (half_w, 0))

        # 中央に薄い区切り線
        from PIL import ImageDraw
        draw = ImageDraw.Draw(canvas)
        draw.line([(half_w, 0), (half_w, H)], fill=(255, 255, 255), width=3)

        canvas.save(output_path, 'JPEG', quality=85)
        return True
    except Exception as e:
        print(f"  [smart_thumb] composite err: {e}")
        return False


def select_thumbnail(title, body='', post_id=''):
    """記事テーマに合ったサムネイルを選択

    Returns:
        dict with 'path', 'source', 'attribution' etc.
        None if no suitable image found.
    """
    analysis = analyze_article_subjects(title, body)
    art_type = analysis['type']
    subjects = analysis['subjects']
    groups = analysis['groups']

    print(f"  [smart_thumb] type={art_type} subjects={subjects} groups={groups}")

    if art_type == 'group' and subjects:
        # グループ画像
        return _resolve_image(subjects[0], post_id)

    elif art_type == 'solo' and subjects:
        # ソロ画像 → 見つからなければグループ画像
        result = _resolve_image(subjects[0], post_id)
        if result:
            return result
        if groups:
            return _resolve_image(groups[0], post_id)

    elif art_type == 'duo' and len(subjects) >= 2:
        # 2人分割合成
        img1 = _resolve_image(subjects[0], post_id)
        img2 = _resolve_image(subjects[1], post_id)
        if img1 and img2:
            output = f'/tmp/duo_thumb_{post_id}.jpg'
            if _composite_duo(img1['image_path'], img2['image_path'], output):
                return {
                    'path': output,
                    'image_path': output,
                    'source': 'duo_composite',
                    'attribution': f'{subjects[0]} + {subjects[1]}',
                }
        # 片方だけなら片方を使用
        return img1 or img2

    elif art_type == 'multi_group':
        # 最初のグループの画像を使用
        if subjects:
            return _resolve_image(subjects[0], post_id)

    # abstract or fallback → DALL-E
    return None


if __name__ == '__main__':
    # テスト
    tests = [
        "BTSが東京ドーム公演を発表",
        "BTSのVがジョングクへの発言で批判",
        "G-DragonとKarinaの交流が話題",
        "K-POPアイドルの美肌の秘密",
        "IVE vs LE SSERAFIM 徹底比較",
        "NCT WISHがMusic Bankで1位獲得",
    ]
    for t in tests:
        r = analyze_article_subjects(t)
        print(f"  {t[:35]:35s} → type={r['type']:12s} subjects={r['subjects']}")
