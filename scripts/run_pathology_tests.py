import asyncio
import csv
import json
import os
import sys
import time
import traceback
import unicodedata
from typing import List, Dict, Any

# Ensure parent directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import AsyncSessionLocal
from app.modules.search.service import search_food
from app.modules.search.schemas import SearchResponse
from google import genai
from google.genai import types

# Path to the CSV test case file
CSV_PATH = "/Users/truongxuanphuc/Documents/01-Graduation-Project/Code/food-recommendation-system/[GTP26] Test case - Test Case bệnh lý.csv"
REPORT_PATH = "/Users/truongxuanphuc/.gemini/antigravity/brain/c71eae85-cf0c-4ac8-bd35-9aec9587de02/pathology_test_report.md"
TAGS_DATA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "standard-data", "tags_data.json")
)

# Initialize Gemini Client for LLM-as-a-Judge
PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

FALSE_POSITIVE_EXCEPTIONS = {
    "Dị ứng động vật thân mềm": [
        "nấm sò",
        "nấm sò nâu",
        "nấm bào ngư",
    ],
    "Dị ứng cá có vây": [
        "cá nhân",
        "cá tính",
    ],
    "Dị ứng sữa bò": [
        "sữa đậu nành",
        "sữa hạt",
    ],
}

_TAG_RULE_CACHE = None

JUDGE_PROMPT = """Bạn là một kiểm thử viên y tế và dinh dưỡng độc lập chuyên đánh giá hệ thống gợi ý món ăn.
Hãy đánh giá kết quả gợi ý của hệ thống đối với test case sau đây:

MÃ TEST CASE: {id}
TÊN TEST CASE (TAG KIỂM CHỨNG): {tag}
NHÓM BỆNH/DỊ ỨNG: {category}
TRUY VẤN CỦA USER: "{query}"
MỤC TIÊU KIỂM THỬ: {objective}
KẾT QUẢ MONG ĐỢI: {expected}

--- KẾT QUẢ THỰC TẾ TỪ HỆ THỐNG ---
1. Các ràng buộc sức khỏe trích xuất được (ai_insight):
   - Exclude (Kiêng): {exclude}
   - Include (Ưu tiên): {include}
   - Prefer (Gợi ý mềm): {prefer}
   - Cảnh báo (warning_message): {warning_message}

2. Danh sách món ăn được đề xuất (Top 5):
{food_results_str}

3. Lời khuyên tự nhiên từ AI (ai_response):
"{ai_response}"

--- YÊU CẦU ĐÁNH GIÁ ---
Hãy phân tích cẩn thận xem kết quả thực tế có tuân thủ đầy đủ "KẾT QUẢ MONG ĐỢI" hay không.
Hãy kiểm tra:
1. Có món ăn nào chứa nguyên liệu bị cấm hay vi phạm quy tắc an toàn không?
2. Câu trả lời của AI có cảnh báo chính xác và rõ ràng về các thành phần xung đột/bệnh lý không?
3. Các sở thích có bị xung đột bừa bãi hay hệ thống có xử lý xung đột hợp lý không?

Hãy quyết định trạng thái kiểm thử là "PASS" (Đạt) hoặc "FAIL" (Không đạt).
Lưu ý: Chỉ ghi FAIL nếu có vi phạm nghiêm trọng về an toàn thực phẩm/y tế hoặc vi phạm trực tiếp Expected Result. Nếu kết quả gợi ý là an toàn nhưng có thể cải thiện nhẹ, hãy đánh giá PASS kèm theo nhận xét.

Định dạng trả về duy nhất dưới dạng JSON sau:
{{
  "status": "PASS" hoặc "FAIL",
  "reason": "Lý do ngắn gọn bằng tiếng Việt giải thích cho quyết định của bạn..."
}}
"""

def parse_csv(csv_path: str) -> List[Dict[str, str]]:
    test_cases = []
    if not os.path.exists(csv_path):
        print(f"❌ File CSV không tồn tại tại: {csv_path}")
        return []
        
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = None
        for row in reader:
            if not row:
                continue
            # Tìm dòng header
            if "Test Case ID" in row:
                header = [col.strip() for col in row]
                continue
            
            if header is not None:
                # Map row by indices
                # CSV format has a leading empty column usually, let's map by finding indices
                id_idx = header.index("Test Case ID")
                cat_idx = header.index("Nhóm")
                tag_idx = header.index("Tag kiểm chứng")
                prompt_idx = header.index("Prompt test")
                obj_idx = header.index("Mục tiêu kiểm thử")
                expected_idx = header.index("Expected Result")
                
                if len(row) > max(id_idx, cat_idx, tag_idx, prompt_idx, obj_idx, expected_idx):
                    tc_id = row[id_idx].strip()
                    if tc_id.startswith("TC-"):
                        test_cases.append({
                            "id": tc_id,
                            "category": row[cat_idx].strip(),
                            "tag": row[tag_idx].strip(),
                            "query": row[prompt_idx].strip(),
                            "objective": row[obj_idx].strip(),
                            "expected": row[expected_idx].strip(),
                            "suggested": row[header.index("Món ăn đang gợi ý")].strip() if "Món ăn đang gợi ý" in header and len(row) > header.index("Món ăn đang gợi ý") else ""
                        })
    return test_cases

def load_tag_exclusion_rules() -> Dict[str, List[str]]:
    """Load hard-check ingredients from standard-data/tags_data.json."""
    global _TAG_RULE_CACHE
    if _TAG_RULE_CACHE is not None:
        return _TAG_RULE_CACHE

    if not os.path.exists(TAGS_DATA_PATH):
        print(f"⚠️ Không tìm thấy tags_data.json tại: {TAGS_DATA_PATH}")
        _TAG_RULE_CACHE = {}
        return _TAG_RULE_CACHE

    with open(TAGS_DATA_PATH, mode="r", encoding="utf-8") as f:
        tags_data = json.load(f)

    rules = {}
    for item in tags_data:
        name = item.get("name")
        exclude_ingredients = item.get("exclude_ingredient") or []
        if name and exclude_ingredients:
            rules[name] = [
                ingredient.strip()
                for ingredient in exclude_ingredients
                if isinstance(ingredient, str) and ingredient.strip()
            ]

    _TAG_RULE_CACHE = rules
    return rules

def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    without_accents = "".join(
        ch for ch in normalized
        if unicodedata.category(ch) != "Mn"
    )
    without_accents = without_accents.replace("đ", "d").replace("Đ", "D")
    return " ".join(without_accents.lower().strip().split())

def phrase_matches(text: str, phrase: str) -> bool:
    text = normalize_text(text)
    phrase = normalize_text(phrase)
    if not text or not phrase:
        return False
    return (
        f" {phrase} " in f" {text} "
        or text.startswith(f"{phrase} ")
        or text.endswith(f" {phrase}")
        or text == phrase
    )

def is_false_positive_match(rule_name: str, text: str, word: str) -> bool:
    text = normalize_text(text)
    word = normalize_text(word)
    exceptions = FALSE_POSITIVE_EXCEPTIONS.get(rule_name, [])
    return any(phrase_matches(text, exception) for exception in exceptions)

def run_programmatic_checks(tc: Dict[str, str], results: List[Dict[str, Any]]) -> List[str]:
    """Chạy các kiểm tra cứng bằng mã nguồn để phát hiện vi phạm nguyên liệu cấm."""
    violations = []
    category = tc["category"]
    tag = tc["tag"]
    
    # Chuẩn hoá text tìm kiếm
    def clean(text):
        return normalize_text(text)
    
    food_names = [clean(r["name"]) for r in results]
    food_ings = []
    for r in results:
        for ing in r.get("ingredients", []):
            food_ings.append(clean(ing))
            
    rules = load_tag_exclusion_rules()
    
    # Đối chiếu
    for key, forbidden_words in rules.items():
        if key in tag or key in category:
            for word in forbidden_words:
                # Kiểm tra xem từ cấm có xuất hiện riêng lẻ trong tên món hoặc nguyên liệu chính không
                for r in results:
                    name_clean = clean(r["name"])
                    # Kiểm tra trùng khớp từ cấm
                    if phrase_matches(name_clean, word) and not is_false_positive_match(key, name_clean, word):
                        violations.append(f"Món ăn '{r['name']}' chứa từ khóa cấm: '{word}'")
                    for ing in r.get("ingredients", []):
                        ing_clean = clean(ing)
                        if phrase_matches(ing_clean, word) and not is_false_positive_match(key, ing_clean, word):
                            violations.append(f"Món '{r['name']}' có nguyên liệu '{ing}' chứa từ khóa cấm: '{word}'")
                            
    return list(set(violations))

async def evaluate_llm_judge(tc: Dict[str, str], actual_response: SearchResponse) -> Dict[str, Any]:
    """Sử dụng Gemini làm giám khảo để chấm điểm an toàn và độ chính xác của phản hồi."""
    # Định dạng danh sách món ăn gợi ý
    food_results_str = ""
    for idx, r in enumerate(actual_response.results, 1):
        food_results_str += f"  #{idx}. {r.name}\n"
        food_results_str += f"       Nguyên liệu chính: {r.core_ingredients}\n"
        food_results_str += f"       Tính chất (soft_tags): {r.soft_tags}\n"
        food_results_str += f"       Vị: {r.taste_profile} | Ngữ cảnh bữa ăn: {r.meal_context} | Ngữ cảnh dịp: {r.occasion_context}\n"
        food_results_str += f"       Lý do gợi ý: {r.reason}\n\n"
        
    prompt = JUDGE_PROMPT.format(
        id=tc["id"],
        tag=tc["tag"],
        category=tc["category"],
        query=tc["query"],
        objective=tc["objective"],
        expected=tc["expected"],
        exclude=actual_response.ai_insight.exclude,
        include=actual_response.ai_insight.include,
        prefer=actual_response.ai_insight.prefer,
        warning_message=actual_response.ai_insight.warning_message,
        food_results_str=food_results_str,
        ai_response=actual_response.ai_response or ""
    )
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "status": types.Schema(type=types.Type.STRING, enum=["PASS", "FAIL"]),
                        "reason": types.Schema(type=types.Type.STRING)
                    },
                    required=["status", "reason"]
                ),
                temperature=0.0
            )
        )
        result = json.loads(response.text)
        return result
    except Exception as e:
        print(f"⚠️ Lỗi khi gọi LLM Judge cho {tc['id']}: {e}")
        return {"status": "FAIL", "reason": f"Lỗi hệ thống LLM Judge: {str(e)}"}

async def run_single_test(tc: Dict[str, str], db) -> Dict[str, Any]:
    """Chạy một test case cụ thể."""
    print(f"🚀 Đang chạy {tc['id']}: {tc['query']}")
    start_time = time.time()
    
    try:
        # Gọi API Search nội bộ
        search_res = await search_food(tc["query"], db)
        latency = (time.time() - start_time) * 1000
        
        # Lấy danh sách kết quả món ăn
        results_list = []
        for r in search_res.results:
            results_list.append({
                "name": r.name,
                "ingredients": r.core_ingredients,
                "soft_tags": r.soft_tags,
                "taste_profile": r.taste_profile,
                "meal_context": r.meal_context,
                "occasion_context": r.occasion_context,
                "reason": r.reason
            })
            
        # 1. Chạy các programmatic check để phát hiện lỗi nghiêm trọng
        prog_violations = run_programmatic_checks(tc, results_list)
        
        # 2. Gọi LLM Judge để chấm điểm
        judge_res = await evaluate_llm_judge(tc, search_res)
        
        # Ghi nhận kết quả cuối cùng
        status = judge_res["status"]
        reason = judge_res["reason"]
        
        # Nếu có vi phạm kiểm tra cứng, ép trạng thái về FAIL
        if prog_violations:
            status = "FAIL"
            reason = f"[Vi phạm nguyên liệu cấm phát hiện tự động]: " + "; ".join(prog_violations) + ". " + reason
            
        print(f"   ➔ Kết quả: {status} ({latency:.0f}ms). Lý do: {reason}\n")
        
        return {
            "id": tc["id"],
            "category": tc["category"],
            "tag": tc["tag"],
            "query": tc["query"],
            "expected": tc["expected"],
            "suggested": tc["suggested"],
            "actual_dishes": [r.name for r in search_res.results],
            "ai_insight": {
                "exclude": search_res.ai_insight.exclude,
                "include": search_res.ai_insight.include,
                "prefer": search_res.ai_insight.prefer,
                "warning_message": search_res.ai_insight.warning_message
            },
            "ai_response": search_res.ai_response,
            "status": status,
            "reason": reason,
            "latency_ms": latency
        }
        
    except Exception as e:
        print(f"❌ Lỗi nghiêm trọng khi chạy {tc['id']}: {e}")
        traceback.print_exc()
        return {
            "id": tc["id"],
            "category": tc["category"],
            "tag": tc["tag"],
            "query": tc["query"],
            "expected": tc["expected"],
            "suggested": tc["suggested"],
            "actual_dishes": [],
            "status": "FAIL",
            "reason": f"Lỗi hệ thống trong lúc chạy test: {str(e)}",
            "latency_ms": 0
        }

async def main():
    print("="*60)
    print("🎬 KHỞI ĐỘNG BỘ TEST CASE BỆNH LÝ & DỊ ỨNG (35 CASES)")
    print("="*60)
    
    test_cases = parse_csv(CSV_PATH)
    if not test_cases:
        print("❌ Không tìm thấy test case nào để chạy!")
        return
        
    print(f"📋 Tìm thấy {len(test_cases)} test case.")
    
    results = []
    
    async with AsyncSessionLocal() as db:
        for idx, tc in enumerate(test_cases, 1):
            res = await run_single_test(tc, db)
            results.append(res)
            # Tránh Rate limit của Gemini API
            await asyncio.sleep(2.0)
            
    # Tổng hợp báo cáo
    passed_cases = [r for r in results if r["status"] == "PASS"]
    failed_cases = [r for r in results if r["status"] == "FAIL"]
    
    pass_rate = (len(passed_cases) / len(results)) * 100
    
    print("\n" + "="*60)
    print("📊 KẾT QUẢ ĐÁNH GIÁ CHUNG")
    print(f"- Tổng số test case: {len(results)}")
    print(f"- Đạt (PASS): {len(passed_cases)}")
    print(f"- Không đạt (FAIL): {len(failed_cases)}")
    print(f"- Tỷ lệ đạt: {pass_rate:.1f}%")
    print("="*60 + "\n")
    
    # Tạo báo cáo Markdown
    report_content = f"""# Pathology and Allergy Recommendation Test Report

**Ngày thực hiện**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Tỷ lệ đạt**: `{pass_rate:.1f}%` ({len(passed_cases)}/{len(results)} đạt)

## 📊 Tổng Quan Kết Quả

| Nhóm kiểm thử | Tổng số | Đạt (PASS) | Không đạt (FAIL) | Tỷ lệ |
|---|---|---|---|---|
| Dị ứng (Allergy) | {len([r for r in results if r['category'] == 'Dị ứng'])} | {len([r for r in results if r['category'] == 'Dị ứng' and r['status'] == 'PASS'])} | {len([r for r in results if r['category'] == 'Dị ứng' and r['status'] == 'FAIL'])} | {len([r for r in results if r['category'] == 'Dị ứng' and r['status'] == 'PASS']) / max(1, len([r for r in results if r['category'] == 'Dị ứng'])) * 100:.1f}% |
| Bệnh lý (Disease) | {len([r for r in results if r['category'] == 'Bệnh lý'])} | {len([r for r in results if r['category'] == 'Bệnh lý' and r['status'] == 'PASS'])} | {len([r for r in results if r['category'] == 'Bệnh lý' and r['status'] == 'FAIL'])} | {len([r for r in results if r['category'] == 'Bệnh lý' and r['status'] == 'PASS']) / max(1, len([r for r in results if r['category'] == 'Bệnh lý'])) * 100:.1f}% |
| Triệu chứng (Symptom) | {len([r for r in results if r['category'] == 'Triệu chứng/tình trạng'])} | {len([r for r in results if r['category'] == 'Triệu chứng/tình trạng' and r['status'] == 'PASS'])} | {len([r for r in results if r['category'] == 'Triệu chứng/tình trạng' and r['status'] == 'FAIL'])} | {len([r for r in results if r['category'] == 'Triệu chứng/tình trạng' and r['status'] == 'PASS']) / max(1, len([r for r in results if r['category'] == 'Triệu chứng/tình trạng'])) * 100:.1f}% |
| Tích hợp (Integrated) | {len([r for r in results if r['category'] == 'Tích hợp'])} | {len([r for r in results if r['category'] == 'Tích hợp' and r['status'] == 'PASS'])} | {len([r for r in results if r['category'] == 'Tích hợp' and r['status'] == 'FAIL'])} | {len([r for r in results if r['category'] == 'Tích hợp' and r['status'] == 'PASS']) / max(1, len([r for r in results if r['category'] == 'Tích hợp'])) * 100:.1f}% |

---

## ❌ Các Test Case Thất Bại (FAIL)
"""
    
    if not failed_cases:
        report_content += "\n> [!NOTE]\n> Tuyệt vời! Không có test case nào thất bại.\n"
    else:
        for idx, fc in enumerate(failed_cases, 1):
            report_content += f"""
### {idx}. {fc['id']}: {fc['tag']}
- **Truy vấn**: "{fc['query']}"
- **Mục tiêu**: {fc['expected']}
- **Món ăn thực tế đề xuất**: {", ".join(fc['actual_dishes'])}
- **Lý do thất bại**: {fc['reason']}
"""
            
    report_content += "\n---\n\n## 📝 Chi Tiết Toàn Bộ Test Case\n\n"
    report_content += "| ID | Nhóm | Tag | Câu Hỏi | Kết Quả Đánh Giá | Trạng thái |\n"
    report_content += "|---|---|---|---|---|---|\n"
    
    for r in results:
        status_icon = "✅ PASS" if r["status"] == "PASS" else "❌ FAIL"
        # Tránh gãy bảng markdown do ký tự xuống dòng
        clean_reason = r["reason"].replace("\n", " ").replace("|", "\\|")
        report_content += f"| {r['id']} | {r['category']} | {r['tag']} | {r['query']} | {clean_reason} | **{status_icon}** |\n"
        
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"💾 Đã lưu báo cáo chi tiết vào: {REPORT_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
