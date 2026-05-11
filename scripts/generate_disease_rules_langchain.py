"""
Sinh bộ luật y khoa bằng LangChain từ dữ liệu thật của dự án.

Input:
- standard-data/tags_data.json                (nguồn danh sách bệnh lý/dị ứng)
- unique_ingredient_names_only.json          (nguồn nguyên liệu đã chuẩn hóa)

Output:
- llm/generated-rules/individual/<disease>.json  (mỗi bệnh 1 file)
- llm/generated-rules/tags_data.generated.json    (file tổng hợp)

Lưu ý:
- Script KHÔNG ghi đè tags_data.json gốc.
- Cần đặt GOOGLE_API_KEY trong environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_vertexai import ChatVertexAI
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID")
MODEL_ID = 'gemini-2.5-pro'

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_TAGS_PATH = PROJECT_ROOT / "standard-data" / "tags_data.json"
DEFAULT_INGREDIENTS_PATH = PROJECT_ROOT / "unique_ingredient_names_only.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "llm" / "generated-rules"


class DiseaseRules(BaseModel):
    name: str = Field(description="Tên bệnh lý hoặc dị ứng")
    tag_type: str = Field(description="Giữ nguyên tag_type từ dữ liệu nguồn")
    exclude_soft_tag: list[str] = Field(
        description="Chỉ chọn từ danh sách soft tags cho trước"
    )
    prefer_soft_tag: list[str] = Field(
        description="Chỉ chọn từ danh sách soft tags cho trước"
    )
    exclude_ingredient: list[str] = Field(
        description="Chỉ chọn từ danh sách nguyên liệu cho trước"
    )
    prefer_ingredient: list[str] = Field(
        description="Chỉ chọn từ danh sách nguyên liệu cho trước"
    )


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def collect_soft_tags(tags_data: list[dict[str, Any]]) -> list[str]:
    all_tags = set()
    for item in tags_data:
        for t in item.get("exclude_soft_tag", []):
            all_tags.add(t)
        for t in item.get("prefer_soft_tag", []):
            all_tags.add(t)
    return sorted(all_tags)


def sanitize_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in name.strip())
    return out.replace(" ", "_")


def build_chain(model_name: str, temperature: float, project_id: str, location: str):
    llm = ChatVertexAI(
        model_name=model_name,
        temperature=temperature,
        project=project_id,
        location=location,
    )
    structured_llm = llm.with_structured_output(DiseaseRules)

    system_prompt = """Bạn là chuyên gia Dinh dưỡng Lâm sàng và kỹ sư dữ liệu y khoa.
Nhiệm vụ: tạo rule y khoa chuẩn cho hệ thống gợi ý món ăn.

[NGUYÊN TẮC BẮT BUỘC]
1) Tuyệt đối không bịa dữ liệu ngoài danh sách cung cấp.
2) exclude_soft_tag và prefer_soft_tag chỉ được chọn từ [DANH SÁCH SOFT TAGS].
3) exclude_ingredient và prefer_ingredient chỉ được chọn từ [DANH SÁCH NGUYÊN LIỆU].
4) tag_type phải giữ nguyên theo input.
5) Hai mảng exclude_ingredient và prefer_ingredient không được trùng nhau.
6) Nếu là ALLERGY: ưu tiên cấm chặt nguyên liệu gây dị ứng và chế phẩm liên quan.
7) Nếu là DISEASE/SYMPTON/STATUS: cân bằng cơ chế bệnh sinh với khả năng ăn uống thực tế.
8) Loại bỏ phần tử trùng lặp trong từng mảng.

[DANH SÁCH SOFT TAGS]
{all_soft_tags}

[DANH SÁCH NGUYÊN LIỆU]
{all_ingredients}
"""

    human_prompt = """Hãy thiết lập bộ luật cho:
- name: {disease_name}
- tag_type: {tag_type}
"""

    prompt_template = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", human_prompt)]
    )
    return prompt_template | structured_llm


def post_validate_rule(
    rule: DiseaseRules, valid_soft_tags: set[str], valid_ingredients: set[str], source_tag_type: str
) -> DiseaseRules:
    cleaned = rule.model_dump()
    cleaned["tag_type"] = source_tag_type

    def _dedupe_keep_order(items: list[str]) -> list[str]:
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    cleaned["exclude_soft_tag"] = [
        x for x in _dedupe_keep_order(cleaned.get("exclude_soft_tag", [])) if x in valid_soft_tags
    ]
    cleaned["prefer_soft_tag"] = [
        x for x in _dedupe_keep_order(cleaned.get("prefer_soft_tag", [])) if x in valid_soft_tags
    ]
    cleaned["exclude_ingredient"] = [
        x for x in _dedupe_keep_order(cleaned.get("exclude_ingredient", [])) if x in valid_ingredients
    ]
    cleaned["prefer_ingredient"] = [
        x for x in _dedupe_keep_order(cleaned.get("prefer_ingredient", [])) if x in valid_ingredients
    ]

    exclude_set = set(cleaned["exclude_ingredient"])
    cleaned["prefer_ingredient"] = [x for x in cleaned["prefer_ingredient"] if x not in exclude_set]
    return DiseaseRules(**cleaned)


def process_single_disease(
    chain,
    disease_name: str,
    tag_type: str,
    all_soft_tags: list[str],
    all_ingredients: list[str],
    output_dir: Path,
) -> dict[str, Any] | None:

    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{sanitize_filename(disease_name)}.json"

    # ==========================================
    # LOGIC 1: BỎ QUA NẾU FILE ĐÃ TỒN TẠI
    # ==========================================
    if file_path.exists():
        print(f"⏭️ Bỏ qua (Đã có sẵn): {disease_name}")
        try:
            with file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"⚠️ File {file_path.name} bị hỏng, tiến hành sinh lại...")

    print(f"⏳ Đang sinh rule cho: {disease_name} ({tag_type})")
    try:
        result: DiseaseRules = chain.invoke(
            {
                "all_soft_tags": json.dumps(all_soft_tags, ensure_ascii=False),
                "all_ingredients": json.dumps(all_ingredients, ensure_ascii=False),
                "disease_name": disease_name,
                "tag_type": tag_type,
            }
        )

        # ==========================================
        # LOGIC 2: BẮT LỖI NONETYPE TỪ VERTEX AI
        # ==========================================
        if result is None:
            print(f"❌ Lỗi: LLM trả về None cho '{disease_name}'. (Có thể do Rate Limit hoặc Safety Filters)")
            return None

        valid_rule = post_validate_rule(
            rule=result,
            valid_soft_tags=set(all_soft_tags),
            valid_ingredients=set(all_ingredients),
            source_tag_type=tag_type,
        )
        payload = valid_rule.model_dump()

        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{sanitize_filename(disease_name)}.json"
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"✅ Đã lưu: {file_path}")

        time.sleep(5)
        return payload
    except ValidationError as e:
        print(f"❌ ValidationError cho '{disease_name}': {e}")
        return None
    except Exception as e:
        print(f"❌ Lỗi khi xử lý '{disease_name}': {e}")
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate medical rules with LangChain")
    parser.add_argument("--tags-file", type=Path, default=DEFAULT_TAGS_PATH)
    parser.add_argument("--ingredients-file", type=Path, default=DEFAULT_INGREDIENTS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", type=str, default="gemini-2.5-flash")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--location", type=str, default="us-central1")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Giới hạn số rule để test nhanh (0 = chạy toàn bộ)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    if not PROJECT_ID:
        raise RuntimeError("Thiếu PROJECT_ID trong môi trường.")

    tags_data: list[dict[str, Any]] = load_json(args.tags_file)
    all_ingredients: list[str] = load_json(args.ingredients_file)
    all_soft_tags = [
        # Vị chủ đạo
        "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
        # Nhiệt độ & cảm giác
        "Nóng hổi", "Thanh mát/Giải nhiệt", "Món lạnh", "Giải rượu", "Giải cảm", "Ấm bụng",
        # Kết cấu
        "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm", "Sống/Chín tái",
        # Dạng món
        "Món nước", "Món khô", "Nước sền sệt",
        # Phương pháp chế biến
        "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào",
        "Gỏi / Nộm / Trộn", "Cuốn / Gói", "Hầm / Ninh",
        "Lẩu", "Kho/Rim", "Súp", "Cháo", "Rang",
        # Dinh dưỡng
        "Thức ăn nhanh", "Món chay", "Hải sản", 
        "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột",
        "Nội tạng", "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
        # Tiêu hoá
        "Dễ tiêu", "Khó tiêu / Nặng bụng", "Healthy / Eat Clean", "Nhiều dầu mỡ / Calo cao",
    ]

    chain = build_chain(
        model_name=MODEL_ID,
        temperature=0.2,
        project_id=PROJECT_ID,
        location="us-central1",
    )

    diseases = [{"name": x["name"], "tag_type": x["tag_type"]} for x in tags_data]
    if args.limit > 0:
        diseases = diseases[: args.limit]

    output_individual_dir = args.output_dir / "individual"
    generated_rules: list[dict[str, Any]] = []

    for item in diseases:
        result = process_single_disease(
            chain=chain,
            disease_name=item["name"],
            tag_type=item["tag_type"],
            all_soft_tags=all_soft_tags,
            all_ingredients=all_ingredients,
            output_dir=output_individual_dir,
        )
        if result:
            generated_rules.append(result)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    merged_path = args.output_dir / "tags_data.generated.json"
    with merged_path.open("w", encoding="utf-8") as f:
        json.dump(generated_rules, f, ensure_ascii=False, indent=2)

    print("\n==============================")
    print(f"✅ Hoàn tất: {len(generated_rules)}/{len(diseases)} rule")
    print(f"📦 File tổng: {merged_path}")
    print("==============================")


if __name__ == "__main__":
    main()
