"""
BizDev問い合わせハンドラ

Usage:
  python3 lib/bizdev_handler.py receive '{"type":"ad","company":"A社","detail":"バナー掲載希望"}'
  python3 lib/bizdev_handler.py list
  python3 lib/bizdev_handler.py review <inquiry_id>
  python3 lib/bizdev_handler.py status <inquiry_id> <accepted|rejected> [reason]

審査フロー（§14準拠）:
  一次: サンダース（自動分類・受付）
  採算: ニャース（収益性判断）
  リスク: アブソル（リスク審査）
  財務: ミュウツー（財務判断）
  最終: アルセウス（最終承認）
"""
import json, sys, os
from datetime import datetime
from pathlib import Path
import uuid

BASE_DIR = Path(__file__).resolve().parent.parent
INQUIRIES_FILE = BASE_DIR / "logs" / "bizdev_inquiries.jsonl"
TEMPLATES_DIR = BASE_DIR / "config" / "bizdev_templates"

# 問い合わせタイプ
INQUIRY_TYPES = {
    "ad": {"label": "広告掲載", "priority": "high", "reviewer": "ニャース"},
    "collaboration": {"label": "タイアップ", "priority": "high", "reviewer": "ニャース"},
    "interview": {"label": "取材依頼", "priority": "medium", "reviewer": "サンダース"},
    "partnership": {"label": "提携相談", "priority": "high", "reviewer": "ミュウツー"},
    "media_inquiry": {"label": "媒体資料請求", "priority": "low", "reviewer": "サンダース"},
    "other": {"label": "その他", "priority": "low", "reviewer": "サンダース"},
}

# NG案件キーワード
NG_KEYWORDS = [
    "アダルト", "ギャンブル", "マルチ", "ネズミ講", "出会い系",
    "違法", "カジノ", "闇", "詐欺", "偽ブランド",
]


def classify_inquiry(detail):
    """問い合わせ内容を自動分類"""
    detail_l = detail.lower()
    if any(w in detail_l for w in ["広告", "バナー", "掲載", "ad", "banner"]):
        return "ad"
    if any(w in detail_l for w in ["タイアップ", "コラボ", "タイアップ", "tie-up"]):
        return "collaboration"
    if any(w in detail_l for w in ["取材", "インタビュー", "interview"]):
        return "interview"
    if any(w in detail_l for w in ["提携", "パートナー", "partnership", "業務提携"]):
        return "partnership"
    if any(w in detail_l for w in ["媒体資料", "media kit", "メディアキット"]):
        return "media_inquiry"
    return "other"


def check_ng(detail):
    """NG案件チェック"""
    for kw in NG_KEYWORDS:
        if kw in detail:
            return True, kw
    return False, None


def receive_inquiry(data):
    """問い合わせ受付"""
    if isinstance(data, str):
        data = json.loads(data)

    inquiry_id = str(uuid.uuid4())[:8]
    detail = data.get("detail", "")
    company = data.get("company", "不明")

    # 自動分類
    inq_type = data.get("type") or classify_inquiry(detail)
    type_info = INQUIRY_TYPES.get(inq_type, INQUIRY_TYPES["other"])

    # NGチェック
    is_ng, ng_word = check_ng(detail)

    inquiry = {
        "id": inquiry_id,
        "received_at": datetime.now().isoformat(),
        "company": company,
        "type": inq_type,
        "type_label": type_info["label"],
        "priority": type_info["priority"],
        "detail": detail,
        "contact": data.get("contact", ""),
        "status": "ng_rejected" if is_ng else "received",
        "ng_reason": f"NGキーワード検出: {ng_word}" if is_ng else None,
        "review_flow": {
            "thunders": "auto_classified",  # サンダース: 一次仕分け
            "meowth": "pending",            # ニャース: 採算判断
            "absol": "pending",             # アブソル: リスク審査
            "mewtwo": "pending",            # ミュウツー: 財務判断
            "arceus": "pending",            # アルセウス: 最終承認
        },
        "assigned_reviewer": type_info["reviewer"],
    }

    # 保存
    INQUIRIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INQUIRIES_FILE, "a") as f:
        f.write(json.dumps(inquiry, ensure_ascii=False) + "\n")

    return inquiry


def list_inquiries(status_filter=None):
    """問い合わせ一覧"""
    if not INQUIRIES_FILE.exists():
        return []
    inquiries = []
    for line in INQUIRIES_FILE.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if status_filter is None or d.get("status") == status_filter:
                inquiries.append(d)
        except json.JSONDecodeError:
            continue
    return inquiries


def update_status(inquiry_id, new_status, reason=""):
    """ステータス更新"""
    if not INQUIRIES_FILE.exists():
        return None

    lines = INQUIRIES_FILE.read_text().strip().split("\n")
    updated = None
    new_lines = []

    for line in lines:
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if d.get("id") == inquiry_id:
                d["status"] = new_status
                d["updated_at"] = datetime.now().isoformat()
                if reason:
                    d["decision_reason"] = reason
                updated = d
            new_lines.append(json.dumps(d, ensure_ascii=False))
        except json.JSONDecodeError:
            new_lines.append(line)

    INQUIRIES_FILE.write_text("\n".join(new_lines) + "\n")
    return updated


def generate_response(inquiry):
    """自動応答テンプレート生成"""
    inq_type = inquiry.get("type", "other")
    company = inquiry.get("company", "御社")
    status = inquiry.get("status", "received")

    if status == "ng_rejected":
        return f"お問い合わせありがとうございます。恐れ入りますが、現在お取り扱いしていない案件のため、ご期待に添えかねます。"

    templates = {
        "ad": f"{company}様\nお問い合わせありがとうございます。広告掲載のご相談を承りました。\n媒体資料をお送りいたしますので、ご確認の上、掲載プランをご検討ください。\n担当より2営業日以内にご連絡いたします。",
        "collaboration": f"{company}様\nタイアップのご相談ありがとうございます。\n企画内容を確認の上、担当より2営業日以内にご連絡いたします。",
        "interview": f"{company}様\n取材のお申し込みありがとうございます。\n内容を確認の上、可否をご連絡いたします。",
        "partnership": f"{company}様\n提携のご相談ありがとうございます。\n経営陣にて検討の上、ご連絡いたします。",
        "media_inquiry": f"{company}様\n媒体資料のご請求ありがとうございます。\n最新の媒体資料をお送りいたします。",
        "other": f"{company}様\nお問い合わせありがとうございます。\n内容を確認の上、担当よりご連絡いたします。",
    }

    return templates.get(inq_type, templates["other"])


def format_inquiry_list(inquiries):
    if not inquiries:
        return "問い合わせなし"
    lines = ["=== BizDev 問い合わせ一覧 ===", ""]
    lines.append(f"{'ID':<10} {'ステータス':<12} {'タイプ':<10} {'企業':<15} {'優先度':<6} {'受付日':<12}")
    lines.append("-" * 70)
    for inq in inquiries:
        lines.append(
            f"{inq['id']:<10} {inq['status']:<12} {inq.get('type_label',''):<10} "
            f"{inq['company']:<15} {inq['priority']:<6} {inq['received_at'][:10]:<12}"
        )
    return "\n".join(lines)


def format_review(inquiry):
    lines = [f"=== 問い合わせ詳細: {inquiry['id']} ===", ""]
    lines.append(f"企業: {inquiry['company']}")
    lines.append(f"タイプ: {inquiry.get('type_label', inquiry['type'])}")
    lines.append(f"優先度: {inquiry['priority']}")
    lines.append(f"ステータス: {inquiry['status']}")
    lines.append(f"受付日: {inquiry['received_at']}")
    lines.append(f"担当: {inquiry.get('assigned_reviewer', 'N/A')}")
    lines.append(f"\n内容:\n  {inquiry['detail']}")
    lines.append(f"\n審査フロー:")
    flow = inquiry.get("review_flow", {})
    for role, status in flow.items():
        icon = {"auto_classified": "done", "pending": "...", "approved": "OK", "rejected": "NG"}.get(status, status)
        lines.append(f"  {role}: {icon}")
    lines.append(f"\n自動応答案:\n  {generate_response(inquiry)}")
    return "\n".join(lines)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "list"

    if command == "receive":
        data = sys.argv[2] if len(sys.argv) > 2 else '{}'
        result = receive_inquiry(data)
        if result["status"] == "ng_rejected":
            print(f"NG案件として自動拒否: {result['ng_reason']}")
        else:
            print(f"受付完了: ID={result['id']} タイプ={result['type_label']} 優先度={result['priority']}")
            print(f"担当: {result['assigned_reviewer']}")
            print(f"\n自動応答案:\n{generate_response(result)}")

    elif command == "list":
        status_filter = sys.argv[2] if len(sys.argv) > 2 else None
        inquiries = list_inquiries(status_filter)
        print(format_inquiry_list(inquiries))

    elif command == "review":
        inquiry_id = sys.argv[2] if len(sys.argv) > 2 else ""
        inquiries = list_inquiries()
        found = [i for i in inquiries if i["id"] == inquiry_id]
        if found:
            print(format_review(found[0]))
        else:
            print(f"ID {inquiry_id} の問い合わせが見つかりません")

    elif command == "status":
        inquiry_id = sys.argv[2] if len(sys.argv) > 2 else ""
        new_status = sys.argv[3] if len(sys.argv) > 3 else ""
        reason = sys.argv[4] if len(sys.argv) > 4 else ""
        result = update_status(inquiry_id, new_status, reason)
        if result:
            print(f"ステータス更新: {inquiry_id} → {new_status}")
        else:
            print(f"ID {inquiry_id} が見つかりません")

    else:
        print("Usage: python3 lib/bizdev_handler.py [receive|list|review|status] ...")
