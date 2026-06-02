"""
Audit file relabel output để tìm các soft_tag đáng nghi.

Ví dụ:
python scripts/audit_soft_tag_output.py \
  --input raw_foods_enriched.sample_seed20260512.json \
  --report soft_tag_audit_report.md
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import relabel_soft_tags as rules


def lower_join(parts):
    return " ".join(str(part).lower() for part in parts if part)


def food_text(item):
    return lower_join([
        item.get("name", ""),
        " ".join(item.get("ingredients", [])),
        " ".join(item.get("raw_ingredients", [])),
        item.get("raw_instructions", ""),
    ])


def add_issue(issues, item, severity, code, message):
    issues.append({
        "severity": severity,
        "code": code,
        "name": item.get("name", "Không rõ tên"),
        "source_index": item.get("source_index"),
        "tags": item.get("soft_tags", []),
        "message": message,
    })


def expected_method_from_name(name_lower, full_text):
    if "bánh gói" in name_lower:
        return None
    if "bánh mì nướng kiểu pháp" in name_lower or "french toast" in full_text:
        return "Chiên / Rán"

    checks = [
        ("Lẩu", ["lẩu"]),
        ("Cháo", ["cháo"]),
        ("Súp", ["súp", "soup"]),
        ("Chiên / Rán", ["chiên", "rán"]),
        ("Nướng", ["nướng"]),
        ("Hấp / Luộc", ["hấp", "luộc"]),
        ("Xào", ["xào"]),
        ("Gỏi / Nộm / Trộn", ["gỏi", "nộm", "trộn", "salad"]),
        ("Cuốn / Gói", ["cuốn", "gói"]),
        ("Kho / Rim", ["kho", "rim"]),
        ("Rang", ["rang"]),
    ]
    for tag, keywords in checks:
        if rules.has_phrase(name_lower, keywords):
            return tag
    return None


def audit_item(item):
    issues = []
    name_lower = item.get("name", "").lower()
    tags = item.get("soft_tags", [])
    tag_set = set(tags)
    ingred_text = lower_join(item.get("ingredients", []))
    full_text = food_text(item)

    invalid_tags = [tag for tag in tags if tag not in rules.VALID_SOFT_TAGS]
    if invalid_tags:
        add_issue(issues, item, "P0", "invalid_tag", f"Tag không nằm trong whitelist: {invalid_tags}")

    if not 3 <= len(tags) <= 8:
        add_issue(issues, item, "P0", "bad_tag_count", f"Số lượng tag = {len(tags)}, cần nằm trong khoảng 3-8")

    form_tags = [tag for tag in tags if tag in rules.FORM_TAGS]
    if len(form_tags) != 1:
        add_issue(issues, item, "P0", "bad_form_count", f"Cần đúng 1 tag dạng món, hiện có: {form_tags}")

    if not tag_set.intersection(rules.METHOD_TAGS):
        add_issue(issues, item, "P0", "missing_method", "Thiếu tag phương pháp chế biến")

    if not tag_set.intersection(rules.TASTE_TAGS):
        add_issue(issues, item, "P0", "missing_taste", "Thiếu tag vị chủ đạo")

    expected_form = rules.choose_form_tag(item.get("name", ""), full_text, tags)
    if form_tags and expected_form not in form_tags:
        add_issue(issues, item, "P1", "suspicious_form", f"Dạng món có vẻ lệch: hiện {form_tags}, rule gợi ý {expected_form}")

    expected_method = expected_method_from_name(name_lower, full_text)
    if expected_method and expected_method not in tag_set:
        add_issue(issues, item, "P1", "method_name_mismatch", f"Tên món gợi ý '{expected_method}' nhưng tag hiện tại không có")

    if "Ngọt" in tag_set and not rules.is_dessert_like(name_lower, tags):
        add_issue(issues, item, "P1", "sweet_false_positive", "Có 'Ngọt' nhưng tên/tag không cho thấy đây là món ngọt/tráng miệng")

    if "Mặn" in tag_set and not rules.has_category_signal(name_lower, rules.SALTY_DISH_KEYWORDS):
        add_issue(issues, item, "P1", "salty_false_positive", "Có 'Mặn' nhưng không phải món mặn đặc trưng kiểu mắm/khô/muối")

    if "Chua" in tag_set:
        has_sour_identity = rules.has_category_signal(name_lower, rules.SOUR_DISH_KEYWORDS)
        has_sour_core = rules.has_category_signal(name_lower + " " + ingred_text, rules.SOUR_CORE_KEYWORDS)
        if not (has_sour_identity or has_sour_core):
            add_issue(issues, item, "P1", "sour_false_positive", "Có 'Chua' nhưng chua có thể chỉ là gia vị/ăn kèm")

    if "Cay" in tag_set:
        has_spicy_identity = rules.has_category_signal(name_lower, rules.SPICY_DISH_KEYWORDS)
        has_spicy_core = rules.has_category_signal(name_lower + " " + ingred_text, rules.SPICY_CORE_KEYWORDS)
        if not (has_spicy_identity or has_spicy_core):
            add_issue(issues, item, "P1", "spicy_false_positive", "Có 'Cay' nhưng ớt/tiêu có thể chỉ là gia vị phụ")

    if "Béo ngậy" in tag_set:
        has_rich_core = rules.has_category_signal(name_lower + " " + ingred_text, rules.RICH_CORE_KEYWORDS)
        if not (has_rich_core or {"Chiên / Rán", "Từ sữa / Phô mai", "Bánh ngọt"} & tag_set):
            add_issue(issues, item, "P1", "rich_false_positive", "Có 'Béo ngậy' nhưng chưa thấy nguyên liệu/cách nấu tạo độ béo rõ")

    is_noodle_dish = rules.has_any(name_lower, rules.NOODLE_DISH_KEYWORDS)
    if is_noodle_dish and "Giòn / Giòn rụm" in tag_set and not rules.has_any(name_lower, rules.CRUNCHY_MAIN_NAME_KEYWORDS):
        add_issue(issues, item, "P1", "texture_topping_crunchy", "Món mì/bún/phở có 'Giòn' có thể do topping/đồ ăn kèm")

    if is_noodle_dish and "Dai / Sần sật" in tag_set and not rules.has_any(ingred_text, rules.CHEWY_MAIN_INGREDIENT_KEYWORDS):
        add_issue(issues, item, "P1", "texture_noodle_chewy", "Món mì/bún/phở có 'Dai' nhưng không có thành phần dai nổi bật")

    has_seafood = rules.has_seafood_signal(ingred_text)
    seafood_in_name = rules.has_seafood_signal(name_lower) or "hải sản" in name_lower
    if has_seafood and "Hải sản" not in tag_set:
        add_issue(issues, item, "P1", "missing_seafood", "Có nguyên liệu hải sản nhưng thiếu tag 'Hải sản'")
    if not has_seafood and "Hải sản" in tag_set:
        add_issue(issues, item, "P1", "seafood_false_positive", "Có tag 'Hải sản' nhưng ingredients không thấy hải sản")
    if has_seafood and not seafood_in_name:
        add_issue(issues, item, "P2", "hidden_seafood_in_ingredients", "Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc")

    if "chay" in name_lower and has_seafood:
        add_issue(issues, item, "P1", "vegetarian_conflict", "Tên món là chay nhưng ingredients có hải sản")

    has_offal = rules.has_offal_signal(ingred_text)
    if has_offal and "Nội tạng" not in tag_set:
        add_issue(issues, item, "P1", "missing_offal", "Có nguyên liệu nội tạng nhưng thiếu tag 'Nội tạng'")
    if not has_offal and "Nội tạng" in tag_set:
        add_issue(issues, item, "P1", "offal_false_positive", "Có tag 'Nội tạng' nhưng ingredients không thấy nội tạng")

    has_protein = rules.has_phrase(ingred_text, rules.PROTEIN_CORE_KEYWORDS)
    if has_protein and "Giàu đạm" not in tag_set and not rules.is_dessert_like(name_lower, tags):
        add_issue(issues, item, "P2", "missing_protein", "Có nguồn đạm rõ nhưng thiếu tag 'Giàu đạm'")
    if not has_protein and "Giàu đạm" in tag_set:
        add_issue(issues, item, "P1", "protein_false_positive", "Có tag 'Giàu đạm' nhưng ingredients không thấy nguồn đạm chính rõ")

    if "Healthy / Eat Clean" in tag_set and (
        {"Chiên / Rán", "Nhiều dầu mỡ / Calo cao", "Béo ngậy", "Thực phẩm chế biến sẵn"} & tag_set
    ):
        add_issue(issues, item, "P2", "healthy_conflict", "'Healthy / Eat Clean' mâu thuẫn với tag dầu mỡ/béo/chế biến sẵn")

    if "Tráng miệng" in tag_set and not rules.is_dessert_like(name_lower, tags):
        add_issue(issues, item, "P2", "dessert_false_positive", "Có 'Tráng miệng' nhưng không giống món ngọt/tráng miệng")

    source_text = full_text
    hallucinated_core = []
    for ingredient in item.get("core_ingredients", []):
        normalized = " ".join(str(ingredient).lower().split())
        if normalized and normalized not in source_text:
            hallucinated_core.append(ingredient)
    if hallucinated_core:
        add_issue(issues, item, "P2", "core_not_grounded", f"Core ingredient không xuất hiện trực tiếp trong source: {hallucinated_core}")

    return issues


def build_report(items, issues):
    by_severity = Counter(issue["severity"] for issue in issues)
    by_code = Counter(issue["code"] for issue in issues)
    affected = len({issue["name"] for issue in issues})
    lines = [
        "# Soft Tag Audit Report",
        "",
        f"- Tổng món audit: {len(items)}",
        f"- Món có cảnh báo: {affected}",
        f"- Tổng cảnh báo: {len(issues)}",
        "",
        "## Theo mức độ",
    ]
    for severity in ["P0", "P1", "P2"]:
        lines.append(f"- {severity}: {by_severity.get(severity, 0)}")

    lines += ["", "## Theo loại cảnh báo"]
    for code, count in by_code.most_common():
        lines.append(f"- `{code}`: {count}")

    grouped = defaultdict(list)
    for issue in issues:
        grouped[(issue["source_index"], issue["name"])].append(issue)

    lines += ["", "## Chi tiết"]
    for (source_index, name), item_issues in grouped.items():
        prefix = f"#{source_index} " if source_index is not None else ""
        tags = item_issues[0]["tags"]
        lines.append("")
        lines.append(f"### {prefix}{name}")
        lines.append(f"- Tags: {', '.join(tags)}")
        for issue in item_issues:
            lines.append(f"- {issue['severity']} `{issue['code']}`: {issue['message']}")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Audit soft_tags sau khi relabel")
    parser.add_argument("--input", required=True, help="File relabel output cần audit")
    parser.add_argument("--report", default="soft_tag_audit_report.md", help="File markdown report")
    args = parser.parse_args()

    input_path = Path(args.input)
    with input_path.open("r", encoding="utf-8") as f:
        items = json.load(f)

    issues = []
    for item in items:
        issues.extend(audit_item(item))

    report = build_report(items, issues)
    Path(args.report).write_text(report, encoding="utf-8")

    print(f"Audited {len(items)} foods")
    print(f"Issues: {len(issues)}")
    print(f"Report: {args.report}")


if __name__ == "__main__":
    main()
