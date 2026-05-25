# Idol Wiki 画像取得パイプライン

Idol Wiki(`idol_artist` CPT, 123組)のロゴ・本人写真を **Wikidata 起点で本人確定**して取得する
スクリプト群。Commons テキスト検索は同名別エンティティを誤マッチするため使わない
(group→QID→P18/P154、person→QID→P18 で固定する)。フリーライセンス(PD/CC)のみ採用し、
取れないものは捏造せず `available:false` でスキップする。

## スクリプト

| ファイル | 役割 | 出力 |
|---|---|---|
| `logos3_wikidata_p154.py` | グループのロゴを Wikidata QID→**P154**(logo image)で取得。QID は description=group/band で曖昧性解消 | `~/.kpop_recovery/batch_logos3/` |
| `logos4_solo_p18.py` | ソロ(members=0)の本人ポートレートを Wikidata QID→**P18** で取得。短い芸名(V/Crush/DEAN等)は本名ヒントで QID 確定 | `~/.kpop_recovery/batch_solo_portraits/` |
| `import_logos3.sh` | batch_logos3 のロゴを `logo_image`+`logo_credit` へ冪等 import(owner 実行) | — |
| `import_solo_portraits.sh` | batch_solo_portraits のポートレートを `logo_image`+`logo_credit` へ冪等 import(owner 実行)。ソロ写真は logo スロットに入れる方針 | — |

## 実行

```bash
# 取得(aiuser、ネットワーク必要、レート制限対応で数分)
python3 tools/idol_wiki/logos4_solo_p18.py            # 全対象
python3 tools/idol_wiki/logos4_solo_p18.py 115 123    # pid 絞り込み

# import は owner(www-data)実行。冪等(既存logo付きはskip)
sudo -u www-data bash tools/idol_wiki/import_solo_portraits.sh
```

## 実績(2026-05-25)

- ロゴ P154: 19組中 **3組取得**(歩留まり16%。公式K-popロゴは大半が著作権ありCommons未収録)。
- ソロ P18: 24組中 **24組取得**(歩留まり100%)。
- 取れない: ロゴ無し16組 / PLAVE(バーチャル=Wikidata実体なし)はプレースホルダ運用が正。

ライセンス帰属は `logo_credit` に格納(CC BY/BY-SA は帰属必須)。
import 先の `<pid>_logo.png` 構造は既存 `import_logos2_verified.sh` と互換。
