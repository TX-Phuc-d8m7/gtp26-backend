"""
Script chuẩn hóa soft_tags, nguyên liệu và mô tả cho TỪNG MÓN ĂN (Single Mode)
bằng LLM (Gemini 2.5 Flash) với JSON Schema mode và Chain-of-Thought.

Chạy: python3 scripts/relabel_single.py [--pilot N] [--start N]
"""

import argparse
import json
import os
import re
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
MODEL_ID = 'gemini-2.5-flash'

# =====================================================================
# DANH SÁCH SOFT TAGS HỢP LỆ
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
    "Món Á", "Món Âu", "Thức ăn nhanh", "Món chay", "Hải sản",
    "Ăn sáng", "Ăn trưa", "Ăn tối", "Ăn chiều / xế", "Ăn khuya", 
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng",
    "Giải rượu", "Giải cảm", "Ấm bụng",
    # Dinh dưỡng
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột",
    "Nội tạng", "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    # Tiêu hoá
    "Dễ tiêu", "Khó tiêu / Nặng bụng", "Healthy / Eat Clean", "Nhiều dầu mỡ / Calo cao",
]

OFFAL_KEYWORDS = ["gan", "lòng", "mề", "óc", "tim", "cật", "dồi", "ruột", "bao tử", "dạ dày", "phèo", "huyết", "tiết", "pín"]
DANANG_KEYWORDS = ["mì quảng", "mỳ quảng", "bún chả cá", "bún mắm nêm", "bún thịt nướng", "bánh tráng cuốn thịt heo", "bánh xèo", "nem lụi", "bánh bèo", "mít non trộn", "ốc hút", "gỏi cá", "tré", "bánh đập", "bún mắm", "cao lầu"]

# Heuristic dictionary: minh bạch hóa rủi ro ẩn từ nguyên liệu
INGREDIENT_RISK_TAG_MAP = {
    "Khó tiêu / Nặng bụng": [
        "thịt vịt", "vịt", "thịt ngan", "ngan", "nội tạng", "gân", "sụn", "da gà", "da vịt"
    ],
    "Béo ngậy": [
        "mỡ heo", "mỡ lợn", "bơ", "phô mai", "sốt phô mai", "kem tươi", "whipping cream",
        "nước cốt dừa", "thịt ba chỉ", "da heo"
    ],
    "Đắng": [
        "ngải cứu", "khổ qua", "mướp đắng", "lá đắng"
    ],
}

def apply_ingredient_risk_heuristics(tags: set[str], ingredient_text: str) -> list[str]:
    logs = []
    for risk_tag, keywords in INGREDIENT_RISK_TAG_MAP.items():
        if any(kw in ingredient_text for kw in keywords) and risk_tag not in tags:
            tags.add(risk_tag)
            logs.append(f"Thêm '{risk_tag}' (heuristic ingredient map)")
    return logs

# =====================================================================
# SYSTEM PROMPT
# =====================================================================
SYSTEM_PROMPT = f"""Bạn là chuyên gia ẩm thực Việt Nam có nhiều năm kinh nghiệm, đồng thời là chuyên gia dinh dưỡng và là FOOD BLOGGER. Dựa trên Tên và Nguyên liệu (ingredients) và cách làm (instructions) hãy dán nhãn soft_tags CHÍNH XÁC cho những món ăn sau, viết mô tả và chuẩn hoá dữ liệu cho danh sách món ăn sau.

    [DANH MỤC TAG HỢP LỆ]
    - Soft Filters: {", ".join(VALID_SOFT_TAGS)}

    ═══════════════════════════════════════════════
    PHẦN 1: QUY TẮC BÓC TÁCH VÀ MÔ TẢ MÓN ĂN
    ═══════════════════════════════════════════════

    [QUY TẮC PHÂN LOẠI NGUYÊN LIỆU (ingredients) - BẮT BUỘC LÀM THEO 4 BƯỚC]
    Bạn phải chạy logic thuật toán sau trong đầu để chia nguyên liệu:

    - BƯỚC 1 (Chuẩn hoá Data gốc): Lấy mảng "ingredients" ban đầu ra. Lập tức RÚT GỌN toàn bộ tên nguyên liệu về dạng Root Noun (VD: "bì sữa tươi không đường" -> "sữa tươi không đường", "500g thịt bò xắt lát" -> "thịt bò"). Ta gọi đây là [Mảng Nguyên Liệu Chuẩn].

    - BƯỚC 2 (Xác định Preprocessing - Chất khử mùi/Ngâm xả): Đọc kỹ "instructions". Tìm các hành động "rửa", "ngâm", "chà xát", "chần", "khử mùi". Rút trích các nguyên liệu đi kèm MÀ SAU ĐÓ BỊ RỬA TRÔI/ĐỔ BỎ (Ví dụ: sữa tươi ngâm gan rồi rửa, chanh để chà cá, muối xát gà, rượu chần thịt). Đưa chúng vào "preprocessing_ingredients". 
    🚨 LƯU Ý: Tuyệt đối KHÔNG đưa nguyên liệu thịt/cá/rau (như gan, ếch, bò...) vào mảng này.

    - BƯỚC 3 (Xác định Core - Nguyên liệu cấu thành): Lấy toàn bộ mảng "ingredients" gốc, CỘNG THÊM các gia vị/nguyên liệu được nhắc đến trong "instructions" (nếu có). Sau đó ĐỐI CHIẾU VÀ LOẠI BỎ hoàn toàn những nguyên liệu đã bị phân vào "preprocessing_ingredients" ở Bước 1. 
        + Nếu một chất (VD: muối, rượu) CHỈ xuất hiện ở hành động sơ chế (Bước 2) -> Xoá nó khỏi Core.
        + TRƯỜNG HỢP ĐA NHIỆM: Nếu một chất (VD: muối) VỪA được dùng để ngâm rửa, VỪA được dùng để tẩm ướp/nấu nước sốt -> Giữ nguyên nó ở Core, VÀ cho phép nó xuất hiện ở cả Preprocessing.        
    - BƯỚC 4 (Kỷ luật chống ảo giác): Tự kiểm tra lại 2 mảng vừa tạo. TUYỆT ĐỐI CHỈ DÙNG những nguyên liệu thực sự xuất hiện trong văn bản gốc ("ingredients" và "instructions"). KHÔNG ĐƯỢC TỰ SUY DIỄN, không được bịa ra nguyên liệu không có trong bài (Ví dụ: Bài không ghi dầu ăn thì không được tự thêm dầu ăn vào).

    [QUY TẮC CHUẨN HOÁ QUAN TRỌNG]
    1. Dữ liệu gốc: Trường "name" giữ nguyên nội dung 100%, trường "ingredients" phải giữ nguyên 100% không thay đổi.
    2. Chuẩn hoá tên: Tên nguyên liệu phải được đưa về dạng Root Noun (VD: "500g thịt bò xắt lát" -> "thịt bò", "1/2 muỗng muối" -> "muối").

    [QUY TẮC VIẾT MÔ TẢ]
    "description": Hãy viết một đoạn văn từ 3-5 câu miêu tả trải nghiệm ăn uống dựa TRÊN CƠ SỞ danh sách nguyên liệu (ingredients) được cung cấp.
    [YÊU CẦU PHONG CÁCH]:
        - Tự nhiên như bài review, gợi cảm xúc.
        - Tập trung vào Khứu giác, Vị giác và Cảm giác (ấm bụng, bùng nổ vị giác, đưa cơm...).
        - Sử dụng từ ngữ đời thường mà người dùng hay dùng khi mô tả mong muốn tìm kiếm.

    [QUY TẮC CỐT LÕI (GROUNDING)]:
    1. Tuyệt đối chỉ suy luận từ "ingredients" được cung cấp. Không tự ý thêm nguyên liệu ngoài danh sách vào mô tả hay dán nhãn.
    4. BẮT BUỘC VỚI NHÃN "Nội tạng": NẾU trong nguyên liệu (ingredients) CÓ CHỨA các thành phần như gan, lòng, mề, óc, tim, cật, dồi, ruột, bao tử, dạ dày, huyết/tiết (của heo, bò, gà...) thì BẠN BẮT BUỘC PHẢI THÊM TAG "Nội tạng" vào mảng "soft_tags".

    ═══════════════════════════════════════════════
    PHẦN 2: QUY TẮC BẮT BUỘC — ĐỌC KỸ TRƯỚC KHI GÁN NHÃN SOFT_TAGS
    ═══════════════════════════════════════════════

    [NHÓM VỊ — YÊU CẦU PHÂN TÍCH TOÀN DIỆN]
    🚨 QUY TẮC CỐT LÕI: TUYỆT ĐỐI KHÔNG DÁN NHÃN THEO KIỂU "TỪ KHÓA NGUYÊN LIỆU". Bạn BẮT BUỘC phải kết hợp đọc TÊN MÓN + NGUYÊN LIỆU + CÁCH LÀM để hiểu TỔNG THỂ BẢN CHẤT món ăn. Đường, muối, chanh, ớt đa phần chỉ là gia vị cân bằng. Chỉ gán nhãn vị giác khi đó là VỊ ĐẶC TRƯNG CHỦ ĐẠO, là thứ đầu tiên người ăn cảm nhận được.

    • "Đậm đà": Đây là nhãn dành cho các món có nước sốt sánh, vị mặn ngọt hài hoà, đậm đà, bám đều lên nguyên liệu (VD: Thịt kho tàu, Bò kho, Vịt kho gừng, Sườn rim mặn ngọt, Gà kho gừng, Thỏ kho tộ, Lòng xào dưa, Cá kho tộ, Vịt rim me, Vịt om sấu).
    • "Thanh đạm": Món ăn nhẹ nhàng, ít gia vị, ít dầu mỡ, giữ vị nguyên bản của nguyên liệu chính (VD: Gà luộc, canh rau ngót, cháo trắng).
    • "Mặn": Chỉ gán cho các món ĐẶC TRƯNG LÀ RẤT MẶN, mang tính chất "ăn dè" (VD: Mắm ruốc, cá khô, kho quẹt, dưa cải muối). TUYỆT ĐỐI KHÔNG gán "Mặn" cho món ăn bình thường chỉ vì có nêm "muối" hay "nước mắm".
    • "Ngọt": Mang bản chất là ĐỒ NGỌT (VD: Chè, tráng miệng, bánh ngọt, kẹo). TUYỆT ĐỐI KHÔNG gán "Ngọt" cho các món ăn mặn (như sườn xào chua ngọt, thịt heo quay) dù trong công thức có ướp nhiều "đường" hay "mật ong".
    • "Chua": Vị chua phải là LINH HỒN CỦA MÓN ĂN (VD: Canh chua cá lóc, lẩu mẻ, gỏi ngó sen). TUYỆT ĐỐI KHÔNG gán "Chua" nếu chanh/giấm/tắc chỉ là gia vị vắt thêm ăn kèm.
    • "Cay": Vị cay là ĐIỂM NHẤN THỐNG TRỊ (VD: Mì cay, lẩu Thái, mực nướng sa tế). KHÔNG gán "Cay" chỉ vì trong công thức có "1 trái ớt" dùng để trang trí hoặc tạo chút vị.
    • "Béo ngậy": Cảm giác béo tràn ngập khoang miệng (VD: Các món nấu nước cốt dừa, lẩu phô mai, xốt bơ tỏi).
    • "Đắng": Vị đắng là đặc trưng cốt lõi (VD: Canh khổ qua/mướp đắng, gà hầm ngải cứu).

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
    
    [NHÓM NĂNG LƯỢNG & ĐẶC TÍNH]
    • "Healthy / Eat Clean": Gán cho món luộc/hấp, nhiều rau, gạo lứt, ức gà.
    • "Nhiều dầu mỡ / Calo cao": Gán cho đồ chiên ngập dầu, phô mai, thịt mỡ.
    • "Hải sản": Bắt buộc gán nếu có tôm, cua, cá, mực, ốc...

    [NHÓM THỜI ĐIỂM BỮA ĂN — BẮT BUỘC TUÂN THỦ]
    • "Ăn sáng": Ưu tiên món nhanh gọn, dễ tiêu (Bún, phở, miến, xôi, bánh mì, cháo).
    • "Ăn trưa" & "Ăn tối" ("Ăn no"): Dành cho món kèm cơm trắng (thịt kho, canh, xào), hoặc món no lâu (Lẩu, Nướng, Cơm tấm).
    • "Ăn vặt" / "Ăn chiều / xế": Món ăn chơi, chua/ngọt, không làm no ngang (Chè, bánh tráng trộn, ốc).
    • "Ăn khuya": Ấm bụng, dễ tiêu (Cháo, súp, mì gõ). TUYỆT ĐỐI KHÔNG gắn cho món nặng bụng như Cơm nếp, Bánh chưng.

    [NHÓM DANH MỤC & ĐỊA PHƯƠNG]
    • "Đặc sản Đà Nẵng": Gán cho các món đặc trưng Đà Nẵng/Quảng Nam: Mì Quảng, Bún chả cá, Bún mắm nêm, Bánh tráng cuốn thịt heo, Cao lầu, Mỳ Quảng, Cơm gà, Bánh xèo miền Trung, Bê thui...
    • "Ẩm thực đường phố": Món thường bán ở hàng quán vỉa hè, xe đẩy, chợ, quán nhỏ
    • "Món Việt truyền thống": Phở, bún bò, cơm tấm, bánh mì, canh, kho, các món thuần Việt phổ biến
    • KHÔNG gán "Món Á", "Món Âu" cho các món Việt Nam thuần túy
    • NỘI TẠNG: Nếu nguyên liệu có gan, lòng, mề, óc, tim, cật, dồi, ruột, bao tử, huyết -> BẮT BUỘC gắn "Nội tạng".

    [QUY TẮC SỐ LƯỢNG]
    • Tối thiểu 3 tags, tối đa 8 tags cho soft_tags (chỉ giữ những tag phù hợp với món nhất, không phù hợp TUYỆT ĐỐI KHÔNG đưa vào)
    • BẮT BUỘC có ít nhất: 1 tag Vị + 1 tag Dạng món + 1 tag Phương pháp
    • Nếu món phù hợp nhiều bữa ăn thì có thể gán đủ tất cả các tag bữa ăn đó

    [YÊU CẦU ĐẦU RA]
    Trả về chính xác mảng JSON tuân thủ tuyệt đối cấu trúc Schema đã được định nghĩa.
    """

# SCHEMA CHỈ TRẢ VỀ OBJECT CHO 1 MÓN
ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "core_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
        "preprocessing_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
        "soft_tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "description": {"type": "STRING"},
        "reasoning": {"type": "STRING", "description": "Giải thích ngắn gọn tại sao chọn các tags này"}
    },
    "required": ["core_ingredients", "preprocessing_ingredients", "soft_tags", "description", "reasoning"]
}

# =====================================================================
# HÀM HẬU XỬ LÝ PYTHON (POST-PROCESSING)
# =====================================================================
def post_process_tags(food_name, raw_ingredients_list, ai_tags):
    tags = set(ai_tags).intersection(VALID_SOFT_TAGS)
    logs = []

    name_lower = food_name.lower()
    ingred_text = " ".join(raw_ingredients_list).lower()
    logs.extend(apply_ingredient_risk_heuristics(tags, ingred_text))

    # --- 1. HARD-MAPPING (Thêm tag bắt buộc) ---
    has_offal = any(re.search(rf'\b{kw}\b', ingred_text) for kw in OFFAL_KEYWORDS)
    if has_offal and "Nội tạng" not in tags:
        tags.add("Nội tạng")
        logs.append("Thêm 'Nội tạng'")
    elif not has_offal and "Nội tạng" in tags:
        tags.discard("Nội tạng")

    if any(kw in name_lower for kw in DANANG_KEYWORDS) and "Đặc sản Đà Nẵng" not in tags:
        tags.add("Đặc sản Đà Nẵng")
        logs.append("Thêm 'Đặc sản Đà Nẵng'")

    if any(kw in name_lower for kw in ["mì quảng", "mỳ quảng", "cao lầu"]):
        tags.discard("Món nước")
        if "Món khô" not in tags:
            tags.add("Nước sền sệt")

    if "cháo" in name_lower:
        tags.update(["Cháo"])
        tags.discard("Món nước")
    elif re.search(r'\b(súp|soup)\b', name_lower):
        tags.update(["Súp"])
        tags.discard("Món nước")

    if re.search(r'\b(bánh mì|bánh mỳ)\b', name_lower):
        tags.update(["Món khô", "Giòn / Giòn rụm"])
        tags.discard("Món nước")
    elif re.search(r'\b(xôi)\b', name_lower):
        tags.update(["Món khô", "Mềm"])
        tags.discard("Món nước")

    if re.search(r'\b(cơm|canh|xào|kho)\b', name_lower):
        tags.update(["Ăn trưa", "Ăn tối"])

    if re.search(r'\b(phô mai|sữa chua|kem|yaourt|bơ|flan|panna cotta|mousse|rau câu|bingsu|chè)\b', name_lower) or \
       re.search(r'\b(sữa tươi|sữa đặc|whipping cream|bơ lạt)\b', ingred_text):
        tags.update(["Từ sữa / Phô mai", "Béo ngậy", "Tráng miệng"])

    # --- 2. KIỂM SOÁT VỊ GIÁC (Chống AI ảo giác theo gia vị) ---
    if "Ngọt" in tags:
        is_dessert = bool({"Tráng miệng", "Bánh ngọt", "Từ sữa / Phô mai"} & tags)
        is_sweet_name = re.search(r'\b(chè|kẹo|bánh|kem|ngọt)\b', name_lower)
        if not (is_dessert or is_sweet_name):
            tags.discard("Ngọt")
            logs.append("Xóa 'Ngọt' (Chỉ có đường nêm nếm)")

    if "Mặn" in tags:
        if not re.search(r'\b(mắm|khô|muối|kho quẹt|chao|muối tiêu)\b', name_lower):
            tags.discard("Mặn")
            logs.append("Xóa 'Mặn' (Dùng tag 'Đậm đà' thay thế)")

    if "Chua" in tags:
        is_salad = bool({"Gỏi / Nộm / Trộn"} & tags)
        has_sour_core = re.search(r'\b(chua|me|sấu|mẻ|giấm|dấm|măng)\b', name_lower + ingred_text)
        if not (is_salad or has_sour_core):
            tags.discard("Chua")
            logs.append("Xóa 'Chua' (Chanh/tắc chỉ là gia vị ăn kèm)")

    # --- 3. MUTUALLY EXCLUSIVE (Loại trừ mâu thuẫn) ---
    if {"Chiên / Rán", "Nhiều dầu mỡ / Calo cao"} & tags:
        for t in ["Thanh đạm", "Healthy / Eat Clean"]:
            if t in tags:
                tags.discard(t)
                logs.append(f"Xóa '{t}' (Trái ngược đồ chiên xào)")

    if {"Tráng miệng", "Bánh ngọt", "Ngọt"} & tags:
        for t in ["Giàu đạm", "Nội tạng", "Mồi nhậu"]:
            if t in tags:
                tags.discard(t)

    return list(tags.intersection(VALID_SOFT_TAGS)), logs

def print_diff(old_tags: list, new_tags: list):
    old_set = set(old_tags)
    new_set = set(new_tags)
    added = new_set - old_set
    removed = old_set - new_set

    if not added and not removed:
        print(f"  ≡  Không thay đổi tags")
    if added:
        print(f"  ✅ Thêm: {sorted(added)}")
    if removed:
        print(f"  ❌ Bỏ:   {sorted(removed)}")

# =====================================================================
# VÒNG LẶP CHÍNH
# =====================================================================
async def main():
    parser = argparse.ArgumentParser(description="Tách nguyên liệu, dán nhãn (Chế độ Single)")
    parser.add_argument("--pilot", type=int, default=0, help="Chỉ chạy N món đầu")
    parser.add_argument("--start", type=int, default=0, help="Bắt đầu từ index N")
    parser.add_argument("--delay", type=int, default=3, help="Thời gian chờ giữa các món")
    args = parser.parse_args()

    input_file = "raw_foods_input.json"
    output_file = "raw_foods_enriched(beta_v2).json"

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            foods = json.load(f)
    except FileNotFoundError:
        print(f"❌ Lỗi: Không tìm thấy file {input_file}")
        sys.exit(1)

    relabeled = []
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                relabeled = json.load(f)
            print(f"📂 Đã tìm thấy {output_file}. Đang có {len(relabeled)} món.")
        except json.JSONDecodeError:
            print(f"⚠️ File lỗi định dạng JSON. Bắt đầu lại từ đầu.")

    start_idx = max(args.start, len(relabeled))
    end_idx = args.pilot if args.pilot > 0 else len(foods)
    foods_to_process = foods[start_idx:end_idx]

    print(f"\n{'='*60}")
    print(f"🏷️  PIPELINE XỬ LÝ (SINGLE MODE) — Bắt đầu từ: {start_idx}")
    print(f"{'='*60}\n")

    if not foods_to_process:
        print("✅ Đã hoàn tất xử lý mọi món ăn. Kết thúc.")
        sys.exit(0)

    for i, item in enumerate(foods_to_process):
        global_idx = start_idx + i
        food_name = item.get("name", "Không rõ tên")
        raw_ingreds = item.get("ingredients", [])
        raw_instructions = item.get("instructions", "")
        old_tags = item.get("soft_tags", [])

        print(f"[{global_idx}] {food_name}")
        
        # Prompt build cho 1 món
        prompt_content = f"""
Tên món: {food_name}
Nguyên liệu gốc: {", ".join(raw_ingreds)}
Cách làm: {raw_instructions}
"""
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[prompt_content],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT, 
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=ITEM_SCHEMA
                )
            )
            
            res = json.loads(response.text)
            
            # Post processing
            cleaned_tags, autofix_logs = post_process_tags(food_name, raw_ingreds, res.get("soft_tags", []))

            # In logs
            if autofix_logs:
                print(f"  🔧 Auto-Fix: {'; '.join(autofix_logs)}")
            print_diff(old_tags, cleaned_tags)
            print(f"  💬 LLM Reasoning: {res.get('reasoning', '')}")

            # Lưu vào danh sách
            enriched_item = {
                "name": food_name,
                "description": res.get("description", ""),
                "core_ingredients": res.get("core_ingredients", []),
                "preprocessing_ingredients": res.get("preprocessing_ingredients", []),
                "soft_tags": cleaned_tags,
                "raw_ingredients": raw_ingreds,
                "raw_instructions": raw_instructions
            }
            relabeled.append(enriched_item)

            # Ghi đè file
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(relabeled, f, ensure_ascii=False, indent=2)

            time.sleep(args.delay) 

        except Exception as e:
            print(f"  ❌ Lỗi: {str(e)}")
            time.sleep(10)
        
        print("-" * 50)

    print(f"\n✅ HOÀN TẤT PIPELINE! Kết quả tại: {output_file}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())