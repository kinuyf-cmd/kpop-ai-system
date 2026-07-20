---
name: acf-field-management
description: KPOP JOURNAL の ACF(Advanced Custom Fields)field 定義のコード管理・JSON 同期・本番移行を扱うメタスキル。field 追加/変更時の操作手順、stg→本番デプロイ runbook、後任者への引き継ぎを成文化。M6(Idol Wiki = E 項目)で新規導入された ACF プラグイン運用の永続化を担う。「ACF」「field 追加」「カスタムフィールド」「JSON 同期」「acf-json」「ACF プラグイン本番反映」「Idol Wiki フィールド変更」といった問い合わせ時に必ず使用。
---

# ACF Field Management

## 1. 目的

M6(段階6.4)で導入された ACF プラグインの field 定義を**コード管理**で
回し、UI 操作だけでは消えてしまう情報の永続化と、stg → 本番への
**確実な移行**を保証する。

オーナー判断(2026-05-20): ACF Free 版採用、JSON 同期必須、関連スキル化。

## 2. 適用範囲(現在の field group)

| group | post type | 保存先 | 主用途 |
|---|---|---|---|
| `group_idol_artist` | `idol_artist` | `acf-json/group_idol_artist.json` | Idol Wiki(M6/E 項目)。15フィールド(名前 3言語、メンバーリピータ、SNS、画像群、SEO) |

将来追加される予定: 引用記事の Layer タグ用 field(M-final 前)、収益化 CTA 配置用 field(M2 = J)。

## 3. JSON 同期の仕組み

子テーマ `generatepress-kpop/functions.php` で:

```php
add_filter( 'acf/settings/save_json', function( $path ) {
    return get_stylesheet_directory() . '/acf-json';
} );
add_filter( 'acf/settings/load_json', function( $paths ) {
    unset( $paths[0] );
    $paths[] = get_stylesheet_directory() . '/acf-json';
    return $paths;
} );
```

これにより、管理画面で field group を保存すると `wp-content/themes/
generatepress-kpop/acf-json/group_<key>.json` に自動書き出しされる。
ファイル単位で Git 管理可能。読み込みも同 path から自動。

## 4. field 追加・変更の標準フロー

1. **管理画面で編集**(/wp-admin/edit.php?post_type=acf-field-group)
2. 保存 → `acf-json/` の該当ファイルが自動更新
3. **作業コピー(`~/.kpop_recovery/stage2/acf-json/`)に取り込む**
   ```
   sudo cp /var/www/wp_stg/wp-content/themes/generatepress-kpop/acf-json/*.json \
       /home/aiuser/.kpop_recovery/stage2/acf-json/
   sudo chown aiuser:aiuser /home/aiuser/.kpop_recovery/stage2/acf-json/*.json
   ```
4. JSON を確認(diff、key 重複、必須フィールド)
5. `deploy_stage9.sh`(またはその後継)で stg → 本番へ反映

**逆方向(コードを正本とする)も可能**: `~/.kpop_recovery/stage2/acf-json/`
を編集して deploy → 管理画面リロードで「Sync available」ボタンが出る
→ 同期。

## 5. 本番反映 runbook(M-final 前)

stg で確定した field 定義を本番に反映する手順:

```
# 1. ACF Free 版を本番にもインストール
sudo -u www-data wp --path=/var/www/wp_<本番> plugin install advanced-custom-fields --activate

# 2. 子テーマを本番にデプロイ(deploy_stage9.sh の DEST を本番に切替)
sudo cp -r /home/aiuser/.kpop_recovery/stage2/acf-json /var/www/wp_<本番>/wp-content/themes/generatepress-kpop/
sudo chown -R www-data:www-data /var/www/wp_<本番>/wp-content/themes/generatepress-kpop/acf-json

# 3. wp-admin にログイン → ACF → Field Groups
#    "Sync available" 表示があれば、すべて選択 → Sync

# 4. /wp-json/wp/v2/idol_artists?per_page=1 で REST 経由のフィールド表示確認
```

## 6. トラブルシューティング

### 6-1. field 値が表示されない
- `function_exists('get_field')` で ACF 有効化を確認
- field name のスペル(JSON 内 `"name"`)と PHP の `get_field('name')` 一致
- Repeater は `while ( have_rows() )` 必須(`get_field` 返り値は配列)

### 6-2. /wp-admin で「Sync available」が出ない
- `acf-json/` ディレクトリの読み取り権限 (www-data)
- ファイル名: `group_<key>.json` の形式必須
- `modified` キーが DB より新しいか確認

### 6-3. 本番移行で field が消えた
- ACF Free と Pro の機能差(Repeater は Free でも使える、Flexible Content は Pro 必須)
- JSON 同期されている path が `acf-json/` に向いているか functions.php 確認
- 子テーマが switched-on になっているか確認

## 7. 関連スキル

- [[kpop-citation-article]] — 引用記事 field を将来追加する場合の連動先
- [[idol-wiki-builder]] — Idol Wiki CPT の上位設計を担うスキル
- [[100point-rubric-judge]] — E 項目採点時にこの skill の運用が前提
- [[audit-rules]] — 月次監査で acf-json/ の差分を集計対象に追加可能

## 8. 後任者への引き継ぎポイント

1. **ACF Pro へのアップグレード不要**(オーナー判断、年1-2回の Free 更新で十分)
2. **JSON 同期は触らない**(functions.php の save_json/load_json フィルタ)
3. **field key の変更禁止**(変更すると既存データが見えなくなる、name はOK)
4. **Repeater 内 sub_field は親 group の field_<key> と整合**(JSON 規約)
5. **本番化前に必ず stg で動作確認**(REST API + 表示テンプレート)
6. **M6 段階6.4 の `group_idol_artist` は Idol Wiki の正本**、削除厳禁
