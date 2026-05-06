"""
Script chuẩn hóa soft_tags cho toàn bộ món ăn trong foods_enriched.json
bằng LLM (Gemini 2.5 Flash) với JSON Schema mode.

Chạy: python3 scripts/relabel_soft_tags.py [--pilot N] [--start N]
  --pilot N : Chỉ chạy N món đầu để review (mặc định: chạy toàn bộ)
  --start N : Bắt đầu từ món thứ N (để tiếp tục nếu bị gián đoạn)
"""

import json
import time
import argparse
import os
import sys
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

# =====================================================================
# DANH SÁCH SOFT TAGS HỢP LỆ (Đã cập nhật với tags mới)
# =====================================================================
VALID_SOFT_TAGS = [
    # Vị chủ đạo
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
    # Nhiệt độ & cảm giác
    "Nóng hổi", "Thanh mát/Giải nhiệt", "Món lạnh",
    # Kết cấu
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm", "Sống/Chín tái",
    # Dạng món
    "Món nước", "Món khô", "Nước sền sệt",
    # Phương pháp chế biến
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào",
    "Gỏi / Nộm / Trộn", "Cuốn / Gói", "Hầm / Ninh",
    "Lẩu", "Kho/Rim", "Súp", "Cháo", "Rang",
    # [NHÓM ĐỊA PHƯƠNG & DANH MỤC — Gán đúng xuất xứ]
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống",
    "Món Á", "Món Âu", "Thức ăn nhanh", "Món chay",
    # Dịp & chức năng (đã tách bữa ăn ra suitable_meals)
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng",
    "Giải rượu", "Giải cảm", "Ấm bụng",
    # Dinh dưỡng
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột",
    "Nội tạng", "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    # Tiêu hóa
    "Dễ tiêu", "Khó tiêu / Nặng bụng"
]

# =====================================================================
# DANH SÁCH BỮA ĂN (Tách riêng khỏi soft tags)
# =====================================================================
VALID_SUITABLE_MEALS = ["Sáng", "Trưa", "Chiều/Xế", "Tối", "Khuya"]

# =====================================================================
# SYSTEM PROMPT — Quy tắc dán nhãn
# =====================================================================
SYSTEM_PROMPT = """Bạn là chuyên gia ẩm thực Việt Nam có nhiều năm kinh nghiệm.
Nhiệm vụ: Gán soft_tags CHÍNH XÁC cho món ăn dựa trên tên, mô tả và nguyên liệu.

═══════════════════════════════════════════════
QUY TẮC BẮT BUỘC — ĐỌC KỸ TRƯỚC KHI GÁN NHÃN
═══════════════════════════════════════════════

[NHÓM VỊ — Chỉ gán nếu là VỊ ĐẶC TRƯNG CHỦ ĐẠO]
• "Đậm đà": Món có chiều sâu hương vị, nước dùng đậm, gia vị phong phú (phở, mì, bún bò, kho tàu)
• "Thanh đạm": Món nhẹ, ít gia vị, thanh nhẹ (cháo trắng, canh rau, luộc)
• "Mặn": Vị mặn là ĐẶC TRƯNG NỔI BẬT (khô mắm, dưa muối, mắm các loại). KHÔNG gán chỉ vì có nước mắm/muối để nêm
• "Ngọt": Vị ngọt là ĐẶC TRƯNG (tráng miệng, chè, bánh ngọt, nước ngọt). KHÔNG gán chỉ vì có đường để nêm
• "Chua": Vị chua là ĐẶC TRƯNG (canh chua, gỏi chua, dưa cải). KHÔNG gán chỉ vì có chanh/giấm để garnish
• "Cay": Vị cay là ĐẶC TRƯNG (bún bò Huế, mì cay, lẩu thái cay). KHÔNG gán chỉ vì có ớt điều chỉnh theo ý thích
• "Béo ngậy": Cảm giác béo rõ rệt khi ăn (lẩu béo, bánh crepe, đồ nướng bơ)
• "Đắng": Vị đắng đặc trưng (khổ qua, ngải cứu, trà đắng)

[NHÓM PHƯƠNG PHÁP — Gán theo cách CHẾ BIẾN CHÍNH]
• Chọn 1 phương pháp chính phù hợp nhất
• Một số món có thể có 2 phương pháp (VD: "Hầm / Ninh" + "Món nước")
• "Hấp / Luộc": Chế biến bằng hơi nước hoặc nước sôi (hải sản hấp, rau luộc, gà luộc, bánh bao hấp). ĐẶC BIỆT chú ý các món có từ "hấp", "luộc" trong tên.
• "Nướng": Chế biến bằng nhiệt trực tiếp (thịt nướng, cá nướng, sườn nướng). ĐẶC BIỆT chú ý các món có từ "nướng" trong tên.
• "Chiên / Rán": Làm chín bằng dầu/mỡ (cá chiên, chả giò rán, bánh xèo).
• "Xào": Đảo nhanh với ít dầu (rau xào, mì xào, bò xào).
• "Kho/Rim": Nấu lửa nhỏ với gia vị mặn ngọt cho keo lại (thịt kho, cá kho, tôm rim).
• "Lẩu": Món nước ăn nóng trực tiếp trên bếp (lẩu thái, lẩu hải sản).
• "Cuốn / Gói": Các món dùng bánh tráng, lá để cuộn nguyên liệu (gỏi cuốn, phở cuốn, chả giò sống).
• "Rang": Rang khô không dầu hoặc ít dầu (lạc rang, tôm rang, cơm rang khô).
• "Gỏi / Nộm / Trộn": Trộn lạnh, gỏi sống/sơ chế, hoặc các món bún/phở trộn.
• PHÂN BIỆT ĐỊNH NGHĨA: 
  - "Hầm / Ninh": Nấu lửa nhỏ thời gian dài để lấy nước ngọt (thường áp dụng cho nước dùng Phở, Bún, Lẩu).
  - "Súp": Món có độ sệt cao (súp cua, súp lươn) hoặc súp kiểu Âu. TUYỆT ĐỐI KHÔNG gán "Súp" cho các món Bún, Phở, Hủ tiếu, Mì truyền thống của Việt Nam.
  - "Cháo": Gạo nấu nát.

[NHÓM DẠNG MÓN — BẮT BUỘC gán 1 trong 3]
• "Món nước": Chan ngập nước dùng lỏng/trong (Phở, Bún nước, Hủ tiếu, Canh...).
• "Món khô": Không có nước dùng, hoặc dạng TRỘN/CHẤM với mắm lỏng/nước tương (Cơm, Bánh mì, Đồ nướng, Bún trộn, Bún thịt nướng, Bún mắm nêm). TUYỆT ĐỐI KHÔNG gán "Nước sền sệt" cho món trộn mắm lỏng.
• "Nước sền sệt": Nước sốt/nước lèo đặc sệt, keo lại, chan xăm xắp (Kho tàu, Cà ri, Mì Quảng, Cao lầu). ⚠️ QUY TẮC ĐẶC BIỆT: Các biến thể của Mì Quảng, Cao Lầu BẮT BUỘC gán "Nước sền sệt" hoặc "Món khô".

[NHÓM BỮA ĂN — Gán vào mảng suitable_meals riêng]
• Có thể gán nhiều bữa nếu phù hợp (Sáng, Trưa, Chiều/Xế, Tối, Khuya)

[NHÓM DỊP & CHỨC NĂNG]
• "Ăn vặt": Bánh, snack, đồ ăn nhẹ
• "Tráng miệng": Chè, bánh ngọt, trái cây
• "Mồi nhậu": Đồ nhắm bia/rượu
• "Ấm bụng": Cháo, súp ấm nóng cho người bệnh/se lạnh

[NHÓM DINH DƯỠNG — Chỉ gán khi rõ ràng]
• "Giàu đạm": Thịt, cá, trứng là thành phần chính
• "Giàu tinh bột": Cơm, bún, phở, bánh mì, xôi, bánh bao là thành phần chính
• "Giàu chất xơ": Nhiều rau củ, đậu.
• "Nội tạng": Có gan, lòng, tim, thận, dồi...
• "Từ sữa / Phô mai": Có sữa, phô mai, yogurt là nguyên liệu chính

[NHÓM KẾT CẤU — CHỈ dựa trên THÀNH PHẦN CHÍNH, KHÔNG tính đồ ăn kèm]
⚠️ QUY TẮC QUAN TRỌNG: Kết cấu phải là đặc trưng của CHÍNH MÓN ĂN, không phải của topping/đồ ăn kèm phụ.

• "Giòn / Giòn rụm":
  - GÁN: Đồ chiên giòn (chả giò, gà rán, bánh xèo), bánh quy, đồ nướng giòn mà CHÍNH MÓN là giòn
  - KHÔNG GÁN: Mì Quảng, Bún, Phở chỉ vì có "bánh tráng nướng", "đậu phộng" ăn kèm
  - KHÔNG GÁN: Các món nước (bún, phở, mì) chỉ vì có topping giòn

• "Dai / Sần sật":
  - GÁN: Thành phần CHÍNH và ĐẶC TRƯNG là dai một cách NỔI BẬT — bò gân, bò gân nấu, mực khô, sụn heo, gân heo, ốc, phá lấu dai
  - KHÔNG GÁN: Mì Quảng, Bún, Phở, Hủ tiếu — sợi mì/bún có độ dai bình thường không phải đặc trưng NỔI BẬT
  - KHÔNG GÁN: Nếu "dai" không phải là lý do người ta chọn hay đặc tả món đó

• "Mềm":
  - GÁN: Kết cấu mềm là ĐẶC TRƯNG — cháo, bánh bao, đậu phụ mềm, trứng hấp
  - GÁN: Thịt hầm nhừ, cá kho mềm

• "Sống/Chín tái":
  - GÁN: Thịt/cá sống hoặc chín tái (gỏi sống, sashimi, nem chua sống, bò tái)
  - KHÔNG GÁN: Rau sống ăn kèm không tính là "Sống / Chín tái"

[NHÓM DANH MỤC & ĐỊA PHƯƠNG]
• "Đặc sản Đà Nẵng": Gán cho các món đặc trưng Đà Nẵng/Quảng Nam: Mì Quảng, Bún chả cá, Bún mắm nêm, Bánh tráng cuốn thịt heo, Cao lầu, Mỳ Quảng, Cơm gà, Bánh xèo miền Trung, Bê thui...
• "Ẩm thực đường phố": Món thường bán ở hàng quán vỉa hè, xe đẩy, chợ, quán nhỏ
• "Món Việt truyền thống": Phở, bún bò, cơm tấm, bánh mì, canh, kho, các món thuần Việt phổ biến
• KHÔNG gán "Món Á", "Món Âu" cho các món Việt Nam thuần túy

[QUY TẮC SỐ LƯỢNG]
• Tối thiểu 6 tags, tối đa 8 tags cho soft_tags (chỉ giữ những tag tinh túy nhất)
• BẮT BUỘC có ít nhất: 1 tag Vị + 1 tag Dạng món + 1 tag Phương pháp
• Đối với suitable_meals: Nếu món phù hợp nhiều bữa thì CÓ THỂ GÁN ĐỦ TẤT CẢ các bữa phù hợp.
"""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "soft_tags": {
            "type": "ARRAY",
            "items": {"type": "STRING", "enum": VALID_SOFT_TAGS},
        },
        "suitable_meals": {
            "type": "ARRAY",
            "items": {"type": "STRING", "enum": VALID_SUITABLE_MEALS},
        },
        "reasoning": {
            "type": "STRING",
            "description": "Giải thích ngắn gọn tại sao chọn các tags này (max 100 chữ)"
        }
    },
    "required": ["soft_tags", "suitable_meals", "reasoning"]
}



# =====================================================================
# POST-PROCESSING — Lọc cứng các tags không hợp lý sau khi LLM trả về
# =====================================================================

# Các từ trong TÊN/NGUYÊN LIỆU chính chỉ ra texture thực sự của món
CRISPY_INDICATORS   = {"chiên", "rán", "nướng giòn", "bánh quy", "phồng", "snack", "cơm cháy", "crackers"}
CHEWY_INDICATORS    = {"gân", "sụn", "mực", "bạch tuộc", "ốc", "bánh đúc dai", "phá lấu", "chân giò"}
SOFT_INDICATORS     = {"cháo", "súp mềm", "đậu phụ", "bánh bao", "bánh flan", "pudding", "chè"}

# Các món thuộc dạng "bún/mì/phở" KHÔNG nên có Giòn hay Dai từ thành phần phụ
NOODLE_SOUP_KEYWORDS = {
    "mì quảng", "bún", "phở", "hủ tiếu", "bánh canh", "mì", "miến",
    "cao lầu", "mỳ quảng"
}

def post_process_tags(food: dict, tags: list[str]) -> list[str]:
    """
    Loại bỏ cứng các texture tags không hợp lý:
    - Giòn / Giòn rụm và Dai / Sần sật không được gán cho món mì/bún/phở
      chỉ vì có bánh tráng, đậu phộng ăn kèm.
    """
    result = list(tags)
    name_lower = food.get("name", "").lower()
    ingredients_lower = " ".join(food.get("core_ingredients", [])).lower()

    # Kiểm tra có phải món nước dạng mì/bún/phở không
    is_noodle_soup = any(kw in name_lower for kw in NOODLE_SOUP_KEYWORDS)

    if is_noodle_soup:
        if "Giòn / Giòn rụm" in result:
            result.remove("Giòn / Giòn rụm")
            print(f"  🔧 [POST-PROCESS] Loại 'Giòn / Giòn rụm' (món nước/mì bún, không tính topping)")

        # Chỉ giữ Dai nếu nguyên liệu chính THỰC SỰ là đồ dai nổi bật
        has_real_chewy = any(ind in name_lower or ind in ingredients_lower
                             for ind in CHEWY_INDICATORS)
        if not has_real_chewy and "Dai / Sần sật" in result:
            result.remove("Dai / Sần sật")
            print(f"  🔧 [POST-PROCESS] Loại 'Dai / Sần sật' (sợi mì/bún không đủ nổi bật)")

    # Xử lý tổng quát: Tránh lạm dụng tag "Súp" cho các món sợi nước lỏng truyền thống
    is_traditional_noodle = any(kw in name_lower for kw in ["bún", "phở", "hủ tiếu", "mì ", "miến", "bánh canh"])
    if is_traditional_noodle and not name_lower.startswith("súp "):
        if "Súp" in result:
            result.remove("Súp")
            print(f"  🔧 [POST-PROCESS] Loại 'Súp' cho Món sợi truyền thống")

    # Xử lý tổng quát: Các món dạng trộn, chấm mắm lỏng phải là "Món khô" (bỏ gỏi/cuốn vì đã có tag phương pháp riêng)
    is_dry_mixed = any(kw in name_lower for kw in ["trộn", "mắm nêm", "thịt nướng", "chấm"])
    if is_traditional_noodle and is_dry_mixed:
        for wrong_tag in ["Nước sền sệt", "Món nước"]:
            if wrong_tag in result:
                result.remove(wrong_tag)
                print(f"  🔧 [POST-PROCESS] Loại '{wrong_tag}' cho món sợi dạng trộn/khô")
        if "Món khô" not in result:
            result.append("Món khô")

    return result


def label_one_food(food: dict, retries: int = 3) -> tuple[list[str], list[str], str]:
    """Gọi LLM để gán soft_tags cho một món ăn."""
    name = food.get("name", "")
    description = food.get("description", "")
    ingredients = ", ".join(food.get("core_ingredients", []))

    prompt = f"""Tên món: {name}
Mô tả: {description}
Nguyên liệu chính: {ingredients}

Hãy gán soft_tags chính xác theo đúng quy tắc trong system prompt."""

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA
                ),
                contents=prompt
            )
            result = json.loads(response.text)
            raw_tags = result.get("soft_tags", [])
            suitable_meals = result.get("suitable_meals", [])
            # Áp dụng post-processing để lọc tags không hợp lý
            clean_tags = post_process_tags(food, raw_tags)
            return clean_tags, suitable_meals, result.get("reasoning", "")
        except Exception as e:
            print(f"    ⚠️  Attempt {attempt+1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(10)

    return food.get("soft_tags", []), food.get("suitable_meals", []), "ERROR: Giữ nguyên tags cũ"


def print_diff(name: str, old_tags: list, new_tags: list):
    """In ra sự khác biệt giữa tags cũ và mới."""
    old_set = set(old_tags)
    new_set = set(new_tags)
    added = new_set - old_set
    removed = old_set - new_set

    if not added and not removed:
        print(f"  ≡  Không thay đổi")
        return

    if added:
        print(f"  ✅ Thêm:  {sorted(added)}")
    if removed:
        print(f"  ❌ Bỏ:   {sorted(removed)}")


def main():
    parser = argparse.ArgumentParser(description="Re-label soft_tags cho món ăn")
    parser.add_argument("--pilot", type=int, default=0,
                        help="Chỉ chạy N món đầu (0 = chạy toàn bộ)")
    parser.add_argument("--start", type=int, default=0,
                        help="Bắt đầu từ index N (để tiếp tục)")
    parser.add_argument("--delay", type=int, default=5,
                        help="Thời gian chờ giữa các request (giây) để tránh rate limit 429")
    args = parser.parse_args()

    # Load dữ liệu
    input_file = "foods_enriched.json"
    output_file = "foods_enriched_v2.json"

    with open(input_file, "r", encoding="utf-8") as f:
        foods = json.load(f)

    # Load output cũ nếu có để tự động bỏ qua các món đã làm
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                relabeled = json.load(f)
            print(f"📂 Đã tìm thấy {output_file}. Tự động tiếp tục từ món thứ {len(relabeled)}")
        except json.JSONDecodeError:
            print(f"⚠️ File {output_file} bị lỗi JSON. Bắt đầu lại từ đầu.")
            relabeled = []
    else:
        relabeled = []

    # Xác định range cần xử lý
    start_idx = max(args.start, len(relabeled))
    end_idx = args.pilot if args.pilot > 0 else len(foods)
    foods_to_process = foods[start_idx:end_idx]

    # Bắt đầu re-label
    mode = f"PILOT ({end_idx} món)" if args.pilot > 0 else f"FULL ({len(foods)} món)"
    print(f"\n{'='*60}")
    print(f"🏷️  RE-LABELING SOFT TAGS — Chế độ: {mode}")
    print(f"   Bắt đầu từ index: {start_idx}")
    print(f"   Cần xử lý: {len(foods_to_process)} món")
    print(f"{'='*60}\n")

    # Copy các món đã xong (nếu tiếp tục)
    if start_idx > 0:
        relabeled = foods[:start_idx]

    stats = {"unchanged": 0, "changed": 0, "errors": 0}

    for i, food in enumerate(foods_to_process):
        global_idx = start_idx + i
        print(f"[{global_idx + 1}/{end_idx}] {food['name']}")

        old_tags = food.get("soft_tags", [])
        new_tags, suitable_meals, reasoning = label_one_food(food)

        if new_tags == old_tags:
            stats["unchanged"] += 1
        else:
            stats["changed"] += 1

        print_diff(food["name"], old_tags, new_tags)
        if reasoning and reasoning != "ERROR: Giữ nguyên tags cũ":
            print(f"  🍽️ Meals: {suitable_meals}")
            print(f"  💬 {reasoning[:120]}")

        # Cập nhật tags
        food_copy = food.copy()
        food_copy["soft_tags"] = new_tags
        food_copy["suitable_meals"] = suitable_meals
        relabeled.append(food_copy)

        # Lưu sau mỗi món (an toàn khi bị gián đoạn)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(relabeled, f, ensure_ascii=False, indent=2)

        print()
        time.sleep(args.delay)  # Tránh rate limit

    # Thống kê kết quả
    print(f"\n{'='*60}")
    print(f"✅ HOÀN TẤT!")
    print(f"   Đã xử lý: {len(foods_to_process)} món")
    print(f"   Thay đổi: {stats['changed']} món")
    print(f"   Giữ nguyên: {stats['unchanged']} món")
    print(f"   Kết quả lưu tại: {output_file}")
    print(f"{'='*60}\n")

    if args.pilot > 0:
        print("💡 Để chạy toàn bộ: python3 scripts/relabel_soft_tags.py")
        print(f"💡 Để tiếp tục từ món {end_idx}: python3 scripts/relabel_soft_tags.py --start {end_idx}")


if __name__ == "__main__":
    main()
