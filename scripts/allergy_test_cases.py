"""Test cases cho 4 loại dị ứng thực phẩm.

Cấu trúc mỗi test case:
  id          : mã định danh duy nhất
  allergy     : loại dị ứng được kiểm tra
  category    : nhóm kịch bản
  label       : mô tả ngắn cho console
  query       : câu hỏi của người dùng
  profile     : UserHealthProfile mock (None = khai báo qua query)
  expect_safe : danh sách tên nguyên liệu/món KHÔNG được xuất hiện trong kết quả
  expect_warn : True nếu kỳ vọng có warning_message
  notes       : giải thích lý do / điểm cần kiểm tra

Chạy cùng compare_pipelines.py:
    from scripts.allergy_test_cases import ALLERGY_TEST_CASES
    TEST_CASES = ALLERGY_TEST_CASES
"""

from __future__ import annotations

from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Helper tạo mock profile (không cần DB)
# ---------------------------------------------------------------------------

def make_profile(
    allergies: list[str] | None = None,
    health_conditions: list[str] | None = None,
    preferred_ingredients: list[str] | None = None,
    taste_profile: list[str] | None = None,
    dish_preferences: list[str] | None = None,
):
    """Tạo UserHealthProfile giả để dùng trong test mà không cần DB."""
    return SimpleNamespace(
        id=None,
        user_id=None,
        allergies=allergies or [],
        health_conditions=health_conditions or [],
        preferred_ingredients=preferred_ingredients or [],
        taste_profile=taste_profile or [],
        dish_preferences=dish_preferences or [],
    )


# ===========================================================================
# NHÓM 1: Dị ứng động vật giáp xác
# Nguồn allergen: tôm, tép, cua, ghẹ, bề bề, chả cua, thanh cua,
#                 mắm tôm, mắm tép, muối tôm, sa tế tôm,
#                 hạt nêm hải sản, gia vị lẩu thái
# Ngoại lệ không bị loại: "tép hành", "tép tỏi"
# ===========================================================================

_GX = "Dị ứng động vật giáp xác"
GIAC_XAC_CASES = [
    {
        "id": "GX-01",
        "allergy": _GX,
        "category": "Xung đột rõ ràng",
        "label": "[GX-01] Người dị ứng giáp xác muốn ăn tôm",
        "query": "Tôi bị dị ứng tôm nhưng hôm nay muốn ăn bún tôm",
        "profile": None,
        "expect_safe": ["tôm", "tép"],
        "expect_warn": True,
        "notes": (
            "Xung đột trực tiếp: user khai báo dị ứng nhưng yêu cầu món có tôm. "
            "Kỳ vọng: warning_message xuất hiện, kết quả trả về món thay thế không có tôm/tép."
        ),
    },
    {
        "id": "GX-02",
        "allergy": _GX,
        "category": "Xung đột rõ ràng",
        "label": "[GX-02] Người dị ứng giáp xác muốn ăn cua",
        "query": "Dị ứng giáp xác, muốn ăn bánh canh cua",
        "profile": None,
        "expect_safe": ["cua", "ghẹ"],
        "expect_warn": True,
        "notes": (
            "Tương tự GX-01 nhưng với cua. Kết quả phải loại bánh canh cua, "
            "trả bánh canh chả, bánh canh giò heo hoặc tương đương."
        ),
    },
    {
        "id": "GX-03",
        "allergy": _GX,
        "category": "Truy vấn trung tính",
        "label": "[GX-03] Truy vấn ăn gì — dị ứng khai báo qua query",
        "query": "Tôi bị dị ứng tôm cua, cho tôi gợi ý ăn trưa",
        "profile": None,
        "expect_safe": ["tôm", "tép", "cua", "ghẹ", "bề bề"],
        "expect_warn": False,
        "notes": (
            "Query trung tính, không yêu cầu món cụ thể. "
            "Hệ thống phải loại hết tôm/cua khỏi pool, kết quả không được có allergen."
        ),
    },
    {
        "id": "GX-04",
        "allergy": _GX,
        "category": "Allergen ẩn trong gia vị",
        "label": "[GX-04] Mắm tôm ẩn trong thành phần",
        "query": "Dị ứng động vật giáp xác, tôi muốn ăn bún đậu mắm tôm",
        "profile": None,
        "expect_safe": ["mắm tôm"],
        "expect_warn": True,
        "notes": (
            "Bún đậu mắm tôm là món đặc trưng có mắm tôm trong core_ingredients. "
            "'mắm tôm' là allergen text pattern của giáp xác. "
            "Kỳ vọng: bị loại bởi allergy text filter."
        ),
    },
    {
        "id": "GX-05",
        "allergy": _GX,
        "category": "Allergen ẩn trong gia vị",
        "label": "[GX-05] Hạt nêm hải sản ẩn trong món",
        "query": "Dị ứng giáp xác, muốn ăn canh chua",
        "profile": None,
        "expect_safe": ["hạt nêm hải sản", "gia vị lẩu thái"],
        "expect_warn": False,
        "notes": (
            "Một số canh chua sử dụng hạt nêm hải sản để tăng vị ngọt. "
            "Nếu core_ingredients ghi 'hạt nêm hải sản' → phải bị loại. "
            "Điểm kiểm tra: allergen ẩn không phải tên món chính."
        ),
    },
    {
        "id": "GX-06",
        "allergy": _GX,
        "category": "Allergen ẩn — chả/thanh cua",
        "label": "[GX-06] Chả cua / thanh cua trong súp/miến",
        "query": "Dị ứng giáp xác, muốn ăn súp",
        "profile": None,
        "expect_safe": ["chả cua", "thanh cua"],
        "expect_warn": False,
        "notes": (
            "Nhiều món súp, bún, miến thêm chả cua hoặc thanh cua. "
            "Cả hai đều là allergen text pattern cho giáp xác. "
            "Kỳ vọng: món nào có 'chả cua'/'thanh cua' trong core_ingredients bị loại."
        ),
    },
    {
        "id": "GX-07",
        "allergy": _GX,
        "category": "Ngoại lệ — không bị loại",
        "label": "[GX-07] Tép hành / tép tỏi KHÔNG được loại",
        "query": "Dị ứng tôm cua, muốn ăn cơm",
        "profile": None,
        "expect_safe": ["tôm", "cua"],
        "expect_warn": False,
        "notes": (
            "EXCLUSION RULE: 'tép' match pattern nhưng 'tép hành', 'tép tỏi' là gia vị thực vật. "
            "Hardcode trong ALLERGEN_TEXT_EXCLUSION_PATTERNS. "
            "Kỳ vọng: món có 'tép hành' / 'tép tỏi' KHÔNG bị loại. "
            "Cần kiểm tra thủ công: xem trong kết quả có món nào ghi tép hành/tép tỏi hay không."
        ),
    },
    {
        "id": "GX-08",
        "allergy": _GX,
        "category": "Profile — dị ứng từ hồ sơ",
        "label": "[GX-08] Dị ứng trong profile, query không đề cập",
        "query": "Tôi muốn ăn gì ngon cho bữa tối",
        "profile": make_profile(allergies=[_GX]),
        "expect_safe": ["tôm", "tép", "cua", "ghẹ", "mắm tôm"],
        "expect_warn": False,
        "notes": (
            "Dị ứng được khai báo qua UserHealthProfile.allergies (không nói trong query). "
            "Hệ thống phải merge profile vào constraints tại resolve_food_conflicts(). "
            "Kỳ vọng: kết quả không có tôm/cua dù query hoàn toàn trung tính."
        ),
    },
    {
        "id": "GX-09",
        "allergy": _GX,
        "category": "Profile — dị ứng + sở thích xung đột",
        "label": "[GX-09] Profile thích tôm nhưng dị ứng giáp xác",
        "query": "Cho tôi gợi ý ăn trưa",
        "profile": make_profile(
            allergies=[_GX],
            preferred_ingredients=["Tôm"],
        ),
        "expect_safe": ["tôm", "tép"],
        "expect_warn": True,
        "notes": (
            "Conflict giữa preferred_ingredients=['Tôm'] và allergies=['Dị ứng động vật giáp xác']. "
            "resolve_food_conflicts() phải phát hiện xung đột và sinh warning_message. "
            "Tôm phải bị loại dù nằm trong preferred_ingredients."
        ),
    },
    {
        "id": "GX-10",
        "allergy": _GX,
        "category": "Kết hợp bệnh lý",
        "label": "[GX-10] Dị ứng giáp xác + Tiểu đường",
        "query": "Tôi bị tiểu đường và dị ứng tôm cua, muốn ăn gì thanh đạm",
        "profile": None,
        "expect_safe": ["tôm", "tép", "cua", "ghẹ"],
        "expect_warn": False,
        "notes": (
            "Kết hợp hai constraints: allergy (loại tôm/cua) + disease (loại đồ ngọt/tinh bột cao). "
            "Kỳ vọng: pool bị thu hẹp từ cả hai phía, kết quả là món thanh đạm không có giáp xác."
        ),
    },
]


# ===========================================================================
# NHÓM 2: Dị ứng động vật thân mềm
# Nguồn allergen: ốc, sò điệp, sò huyết, sò lông, sò lụa, nghêu, ngao,
#                 hến, hàu, vẹm, tu hài, mực, bạch tuộc, dầu hào
# Ngoại lệ không bị loại: "mực trứng" (với dị ứng trứng — xem TC-TR-07)
# ===========================================================================

_TM = "Dị ứng động vật thân mềm"
THAN_MEM_CASES = [
    {
        "id": "TM-01",
        "allergy": _TM,
        "category": "Xung đột rõ ràng",
        "label": "[TM-01] Người dị ứng thân mềm muốn ăn mực",
        "query": "Dị ứng mực ốc, muốn ăn mực xào cần tỏi",
        "profile": None,
        "expect_safe": ["mực", "bạch tuộc"],
        "expect_warn": True,
        "notes": (
            "Xung đột trực tiếp: query đề cập 'mực xào' trong khi dị ứng thân mềm. "
            "Kỳ vọng: warning, kết quả trả món thay thế không có mực/bạch tuộc/ốc."
        ),
    },
    {
        "id": "TM-02",
        "allergy": _TM,
        "category": "Xung đột rõ ràng",
        "label": "[TM-02] Người dị ứng thân mềm muốn ăn ốc",
        "query": "Tôi bị dị ứng đồ biển mềm, nhưng thèm ăn ốc luộc",
        "profile": None,
        "expect_safe": ["ốc", "nghêu", "hến"],
        "expect_warn": True,
        "notes": (
            "User dùng cách diễn đạt khác ('đồ biển mềm') thay vì tên chính xác. "
            "Supervisor LLM cần nhận ra ý định và map đúng về 'Dị ứng động vật thân mềm'. "
            "Kiểm tra fallback rule-based có nhận ra 'dị ứng' kết hợp 'ốc' không."
        ),
    },
    {
        "id": "TM-03",
        "allergy": _TM,
        "category": "Truy vấn trung tính",
        "label": "[TM-03] Query trung tính — dị ứng từ profile",
        "query": "Tôi muốn ăn gì cho bữa tối ngon miệng",
        "profile": make_profile(allergies=[_TM]),
        "expect_safe": ["mực", "ốc", "nghêu", "hàu", "sò", "bạch tuộc", "dầu hào"],
        "expect_warn": False,
        "notes": (
            "Profile khai báo dị ứng thân mềm. Query không đề cập allergen. "
            "Kỳ vọng: toàn bộ thân mềm bị loại khỏi pool trước khi semantic search."
        ),
    },
    {
        "id": "TM-04",
        "allergy": _TM,
        "category": "Allergen ẩn trong gia vị",
        "label": "[TM-04] Dầu hào ẩn trong món xào",
        "query": "Dị ứng thân mềm, muốn ăn rau xào",
        "profile": None,
        "expect_safe": ["dầu hào"],
        "expect_warn": False,
        "notes": (
            "Dầu hào (oyster sauce) là allergen ẩn phổ biến trong món xào Á Đông. "
            "'dầu hào' có trong ALLERGEN_TEXT_PATTERNS của thân mềm. "
            "Kỳ vọng: món rau xào nào ghi 'dầu hào' trong core_ingredients bị loại. "
            "Điểm kiểm tra: allergen ẩn không liên quan đến tên món."
        ),
    },
    {
        "id": "TM-05",
        "allergy": _TM,
        "category": "Ngoại lệ — không bị loại",
        "label": "[TM-05] Nấm sò KHÔNG được loại vì không phải sò biển",
        "query": "Dị ứng nghêu ốc hàu, muốn ăn cơm chay",
        "profile": None,
        "expect_safe": ["nghêu", "ốc", "hàu"],
        "expect_warn": False,
        "notes": (
            "EDGE CASE QUAN TRỌNG: 'nấm sò' hoặc 'nấm sò nâu' là tên nấm, không phải động vật. "
            "FALSE_POSITIVE_EXCEPTIONS trong audit script đã ghi nhận trường hợp này. "
            "Kỳ vọng: món ăn chứa 'nấm sò' KHÔNG bị loại. "
            "Cần kiểm tra xem allergy text filter có nhận 'nấm sò' là pattern 'sò' không."
        ),
    },
    {
        "id": "TM-06",
        "allergy": _TM,
        "category": "Allergen nhiều loại cùng nhóm",
        "label": "[TM-06] Hải sản hỗn hợp — nhiều thân mềm",
        "query": "Dị ứng thân mềm, đề xuất món hải sản phù hợp",
        "profile": None,
        "expect_safe": ["mực", "ốc", "nghêu", "hàu", "sò", "bạch tuộc", "vẹm"],
        "expect_warn": True,
        "notes": (
            "User xin gợi ý 'hải sản' nhưng dị ứng thân mềm. "
            "Kỳ vọng: warning giải thích xung đột, kết quả trả hải sản hợp lệ "
            "(tôm, cá) nếu không dị ứng giáp xác, hoặc trả món không hải sản."
        ),
    },
    {
        "id": "TM-07",
        "allergy": _TM,
        "category": "Kết hợp dị ứng",
        "label": "[TM-07] Dị ứng cả giáp xác + thân mềm",
        "query": "Tôi dị ứng hải sản, muốn ăn gì protein cao",
        "profile": make_profile(allergies=[_TM, "Dị ứng động vật giáp xác"]),
        "expect_safe": ["tôm", "cua", "mực", "ốc", "nghêu", "hàu"],
        "expect_warn": False,
        "notes": (
            "Kết hợp cả hai nhóm dị ứng hải sản. "
            "Kỳ vọng: pool bị loại hầu hết hải sản, kết quả trả thịt/cá/đậu hũ. "
            "Kiểm tra: số lượng món bị loại của hai pipeline có khác nhau không."
        ),
    },
    {
        "id": "TM-08",
        "allergy": _TM,
        "category": "Kết hợp bệnh lý",
        "label": "[TM-08] Dị ứng thân mềm + Gout",
        "query": "Tôi bị Gout và dị ứng mực ốc, muốn ăn bữa trưa nhẹ",
        "profile": None,
        "expect_safe": ["mực", "ốc", "nghêu", "hàu"],
        "expect_warn": False,
        "notes": (
            "Gout đã loại cứng tag 'Hải sản'. Dị ứng thân mềm loại thêm qua ingredient key. "
            "Kết quả pool rất hẹp: phải là món thịt/cá nhẹ, ít purin. "
            "Semantic_first dễ kích hoạt expansion mechanism ở case này."
        ),
    },
]


# ===========================================================================
# NHÓM 3: Dị ứng đậu phộng
# Nguồn allergen: đậu phộng, đậu phụng, lạc, bơ đậu phộng
# Từ tags_data thêm: dau phong rang
# Exclude soft tag: Gỏi / Nộm / Trộn
# ===========================================================================

_DP = "Dị ứng đậu phộng"
DAU_PHONG_CASES = [
    {
        "id": "DP-01",
        "allergy": _DP,
        "category": "Xung đột rõ ràng",
        "label": "[DP-01] Người dị ứng đậu phộng muốn ăn gỏi",
        "query": "Dị ứng đậu phộng, muốn ăn gỏi gà",
        "profile": None,
        "expect_safe": ["đậu phộng", "lạc"],
        "expect_warn": True,
        "notes": (
            "Gỏi gà thường có đậu phộng rang trên mặt. "
            "Conflict: user muốn gỏi nhưng dị ứng đậu phộng. "
            "Kỳ vọng: warning, kết quả trả gỏi gà không có đậu phộng (nếu có) "
            "hoặc món thay thế không chứa đậu phộng."
        ),
    },
    {
        "id": "DP-02",
        "allergy": _DP,
        "category": "Xung đột rõ ràng",
        "label": "[DP-02] Người dị ứng đậu phộng muốn ăn bún bò",
        "query": "Dị ứng lạc đậu phộng, muốn ăn bún bò Huế",
        "profile": None,
        "expect_safe": ["đậu phộng", "lạc"],
        "expect_warn": False,
        "notes": (
            "Bún bò Huế cơ bản không có đậu phộng. "
            "Kỳ vọng: KHÔNG có warning, bún bò Huế vẫn được trả về bình thường. "
            "Kiểm tra: hệ thống không over-filter tất cả món chỉ vì có dị ứng đậu phộng."
        ),
    },
    {
        "id": "DP-03",
        "allergy": _DP,
        "category": "Soft tag exclude",
        "label": "[DP-03] Soft tag 'Gỏi / Nộm / Trộn' bị penalty",
        "query": "Dị ứng đậu phộng, muốn ăn gì tươi mát",
        "profile": None,
        "expect_safe": ["đậu phộng", "lạc"],
        "expect_warn": False,
        "notes": (
            "exclude_soft_tag của dị ứng đậu phộng là 'Gỏi / Nộm / Trộn'. "
            "Legacy pipeline: tất cả tag 'Gỏi/Nộm/Trộn' bị penalty điểm (không loại cứng). "
            "Kỳ vọng: gỏi bò/gỏi gà xuất hiện thấp hơn hoặc bị đẩy xuống cuối bảng xếp hạng. "
            "Điểm so sánh thú vị giữa hai pipeline: semantic sẽ dùng medical_avoid_tags penalty."
        ),
    },
    {
        "id": "DP-04",
        "allergy": _DP,
        "category": "Allergen ẩn trong trang trí",
        "label": "[DP-04] Đậu phộng rang trang trí trong món",
        "query": "Dị ứng đậu phộng, tôi muốn ăn cơm tấm",
        "profile": None,
        "expect_safe": ["đậu phộng", "lạc"],
        "expect_warn": False,
        "notes": (
            "Cơm tấm bì chả thường có đậu phộng rang bên trên hoặc trộn vào bì. "
            "Nếu core_ingredients ghi 'đậu phộng rang' → bị loại. "
            "Kỳ vọng: cơm tấm không có đậu phộng trong core_ingredients vẫn được trả về. "
            "Điểm kiểm tra: allergen ẩn dạng topping/trang trí."
        ),
    },
    {
        "id": "DP-05",
        "allergy": _DP,
        "category": "Allergen ẩn trong sốt/gia vị",
        "label": "[DP-05] Bơ đậu phộng ẩn trong sốt",
        "query": "Dị ứng đậu phộng, muốn ăn bún thịt nướng",
        "profile": None,
        "expect_safe": ["bơ đậu phộng", "đậu phộng"],
        "expect_warn": False,
        "notes": (
            "Một số công thức bún thịt nướng hoặc nước chấm có bơ đậu phộng. "
            "'bơ đậu phộng' là allergen text pattern. "
            "Kỳ vọng: món nào ghi bơ đậu phộng trong core_ingredients bị loại."
        ),
    },
    {
        "id": "DP-06",
        "allergy": _DP,
        "category": "Profile — dị ứng từ hồ sơ",
        "label": "[DP-06] Dị ứng đậu phộng từ profile, query trung tính",
        "query": "Gợi ý món ăn sáng nhẹ nhàng",
        "profile": make_profile(allergies=[_DP]),
        "expect_safe": ["đậu phộng", "lạc"],
        "expect_warn": False,
        "notes": (
            "Profile khai báo dị ứng đậu phộng. Query không đề cập allergen. "
            "Kỳ vọng: đậu phộng bị loại khỏi pool mà không cần user nhắc lại."
        ),
    },
    {
        "id": "DP-07",
        "allergy": _DP,
        "category": "Kết hợp dị ứng",
        "label": "[DP-07] Dị ứng đậu phộng + dị ứng trứng",
        "query": "Tôi dị ứng đậu phộng và trứng, muốn ăn salad hoặc gỏi",
        "profile": make_profile(allergies=[_DP, "Dị ứng trứng"]),
        "expect_safe": ["đậu phộng", "lạc", "trứng", "mayonnaise"],
        "expect_warn": True,
        "notes": (
            "Gỏi/salad thường có cả đậu phộng lẫn mayonnaise (trứng). "
            "Kết hợp hai allergen thu hẹp kết quả đáng kể. "
            "Kỳ vọng: warning vì conflict (muốn gỏi nhưng gỏi thường có đậu phộng), "
            "kết quả trả gỏi đặc biệt không có cả hai allergen."
        ),
    },
]


# ===========================================================================
# NHÓM 4: Dị ứng trứng
# Nguồn allergen: trứng, trứng gà, trứng cút, trứng vịt, trứng vịt lộn,
#                 trứng muối, trứng bắc thảo, trứng non, lòng đỏ/trắng trứng,
#                 chả trứng, mayonnaise, sốt mayonnaise, mì trứng,
#                 bánh flan, kem trứng
# Exclude soft tag: Bánh ngọt, Thực phẩm chế biến sẵn, Từ sữa / Phô mai
# Ngoại lệ không bị loại: "mực trứng" (mực non — không phải trứng gà/vịt)
# ===========================================================================

_TR = "Dị ứng trứng"
TRUNG_CASES = [
    {
        "id": "TR-01",
        "allergy": _TR,
        "category": "Xung đột rõ ràng",
        "label": "[TR-01] Người dị ứng trứng muốn ăn cơm chiên trứng",
        "query": "Dị ứng trứng, muốn ăn cơm chiên dương châu",
        "profile": None,
        "expect_safe": ["trứng"],
        "expect_warn": True,
        "notes": (
            "Cơm chiên dương châu dứt khoát có trứng. "
            "Xung đột rõ: user biết mình dị ứng nhưng vẫn muốn ăn. "
            "Kỳ vọng: warning_message, trả cơm chiên không trứng hoặc món thay thế."
        ),
    },
    {
        "id": "TR-02",
        "allergy": _TR,
        "category": "Xung đột rõ ràng",
        "label": "[TR-02] Dị ứng trứng muốn ăn trứng vịt lộn",
        "query": "Tôi bị dị ứng trứng, hôm nay thèm ăn trứng vịt lộn",
        "profile": None,
        "expect_safe": ["trứng vịt lộn", "trứng"],
        "expect_warn": True,
        "notes": (
            "Xung đột cực rõ ràng. Trứng vịt lộn = 100% trứng. "
            "Kỳ vọng: cảnh báo mạnh, không có món nào chứa trứng trong kết quả."
        ),
    },
    {
        "id": "TR-03",
        "allergy": _TR,
        "category": "Truy vấn trung tính",
        "label": "[TR-03] Query trung tính — dị ứng trứng trong profile",
        "query": "Muốn ăn gì cho bữa sáng",
        "profile": make_profile(allergies=[_TR]),
        "expect_safe": ["trứng", "mayonnaise", "bánh flan"],
        "expect_warn": False,
        "notes": (
            "Profile khai báo dị ứng trứng. Query không nhắc trứng. "
            "Bữa sáng phổ biến ở Việt Nam: bánh mì, xôi, cháo... nhiều món có trứng. "
            "Kỳ vọng: không có trứng/mayonnaise trong kết quả, ưu tiên xôi/cháo/bánh mì không trứng."
        ),
    },
    {
        "id": "TR-04",
        "allergy": _TR,
        "category": "Allergen ẩn — mayonnaise",
        "label": "[TR-04] Mayonnaise ẩn trong salad / bánh mì",
        "query": "Dị ứng trứng, muốn ăn sandwich hoặc bánh mì",
        "profile": None,
        "expect_safe": ["mayonnaise", "sốt mayonnaise"],
        "expect_warn": False,
        "notes": (
            "Bánh mì thịt nguội/sandwich thường phết mayonnaise — làm từ lòng đỏ trứng. "
            "'mayonnaise' và 'sốt mayonnaise' đều là allergen text pattern cho dị ứng trứng. "
            "Kỳ vọng: bánh mì nào có mayonnaise trong core_ingredients bị loại."
        ),
    },
    {
        "id": "TR-05",
        "allergy": _TR,
        "category": "Allergen ẩn — mì trứng",
        "label": "[TR-05] Mì trứng ẩn trong các món mì",
        "query": "Dị ứng trứng, muốn ăn mì",
        "profile": None,
        "expect_safe": ["mì trứng", "trứng"],
        "expect_warn": False,
        "notes": (
            "Phần lớn mì sợi vàng Việt Nam làm từ mì trứng. "
            "'mì trứng' là allergen text pattern, cũng là exclude_ingredient trong tags_data. "
            "Kỳ vọng: mì trứng/mì egg noodle bị loại, bún/phở/hủ tiếu gạo vẫn được trả."
        ),
    },
    {
        "id": "TR-06",
        "allergy": _TR,
        "category": "Allergen ẩn — bánh flan / kem trứng",
        "label": "[TR-06] Dị ứng trứng muốn ăn tráng miệng",
        "query": "Tôi dị ứng trứng, muốn ăn gì ngọt tráng miệng",
        "profile": None,
        "expect_safe": ["bánh flan", "kem trứng", "trứng"],
        "expect_warn": False,
        "notes": (
            "Bánh flan và kem trứng là tráng miệng phổ biến hoàn toàn làm từ trứng. "
            "Cả hai đều là allergen text pattern. "
            "Kỳ vọng: các món tráng miệng này bị loại, trả chè / trái cây / bánh không trứng."
        ),
    },
    {
        "id": "TR-07",
        "allergy": _TR,
        "category": "Ngoại lệ — không bị loại",
        "label": "[TR-07] Mực trứng KHÔNG được loại vì 'dị ứng trứng'",
        "query": "Dị ứng trứng, muốn ăn hải sản",
        "profile": None,
        "expect_safe": ["trứng gà", "trứng vịt"],
        "expect_warn": False,
        "notes": (
            "EXCLUSION RULE QUAN TRỌNG: 'mực trứng' là tên mực non (baby squid), không phải trứng gia cầm. "
            "ALLERGEN_TEXT_EXCLUSION_PATTERNS ghi: ('Dị ứng trứng', 'trứng'): ['mực trứng']. "
            "Kỳ vọng: nếu người dùng không dị ứng thân mềm, 'mực trứng' KHÔNG bị loại. "
            "Cần verify thủ công: kiểm tra kết quả có mực trứng hay không."
        ),
    },
    {
        "id": "TR-08",
        "allergy": _TR,
        "category": "Soft tag exclude",
        "label": "[TR-08] Soft tag 'Bánh ngọt' bị penalty với dị ứng trứng",
        "query": "Dị ứng trứng, muốn ăn vặt bánh",
        "profile": None,
        "expect_safe": ["trứng", "mayonnaise"],
        "expect_warn": False,
        "notes": (
            "exclude_soft_tag của dị ứng trứng: ['Bánh ngọt', 'Thực phẩm chế biến sẵn', 'Từ sữa / Phô mai']. "
            "Bánh ngọt hầu hết có trứng. Kỳ vọng: các món tag 'Bánh ngọt' bị penalty cao, "
            "xuất hiện thấp hơn hoặc không xuất hiện trong top 5."
        ),
    },
    {
        "id": "TR-09",
        "allergy": _TR,
        "category": "Allergen ẩn — lòng đỏ / lòng trắng",
        "label": "[TR-09] Lòng đỏ/lòng trắng trứng trong sốt",
        "query": "Dị ứng trứng, muốn ăn cơm gà",
        "profile": None,
        "expect_safe": ["lòng đỏ trứng", "lòng trắng trứng", "trứng"],
        "expect_warn": False,
        "notes": (
            "Một số món cơm gà có sốt trứng hoặc dùng lòng đỏ trứng làm sốt mặt. "
            "Kỳ vọng: loại nếu core_ingredients ghi 'lòng đỏ trứng'/'lòng trắng trứng'."
        ),
    },
    {
        "id": "TR-10",
        "allergy": _TR,
        "category": "Kết hợp dị ứng",
        "label": "[TR-10] Dị ứng trứng + dị ứng giáp xác",
        "query": "Tôi dị ứng tôm và trứng, gợi ý ăn sáng",
        "profile": make_profile(allergies=[_TR, "Dị ứng động vật giáp xác"]),
        "expect_safe": ["trứng", "tôm", "tép", "mayonnaise", "bánh flan"],
        "expect_warn": False,
        "notes": (
            "Kết hợp hai nhóm dị ứng phổ biến. Nhiều món ăn sáng phổ biến bị loại: "
            "bánh mì trứng, bánh mì tôm, cơm chiên trứng... "
            "Kỳ vọng: trả về xôi, cháo, phở, hoặc món sáng không có hai allergen."
        ),
    },
]


# ===========================================================================
# NHÓM 5: Cross-allergy — kết hợp nhiều nhóm
# ===========================================================================

CROSS_CASES = [
    {
        "id": "CROSS-01",
        "allergy": "Giáp xác + Thân mềm + Trứng",
        "category": "Đa dị ứng",
        "label": "[CROSS-01] Ba nhóm dị ứng cùng lúc",
        "query": "Tôi dị ứng hải sản và trứng, cần ăn gì đủ chất",
        "profile": make_profile(
            allergies=[_TM, "Dị ứng động vật giáp xác", _TR]
        ),
        "expect_safe": ["tôm", "cua", "mực", "ốc", "trứng", "mayonnaise"],
        "expect_warn": False,
        "notes": (
            "Ba nhóm dị ứng lớn cùng lúc. Pool bị thu hẹp rất nhiều. "
            "Semantic_first dễ kích hoạt expansion (safe_count < return_limit). "
            "Kỳ vọng: kết quả là thịt bò/heo/gà, cá, đậu hũ, rau — không có bất kỳ allergen nào. "
            "Điểm so sánh: semantic_first có retrieval expansion, legacy có thể trả ít hơn 5 món."
        ),
    },
    {
        "id": "CROSS-02",
        "allergy": "Đậu phộng + Trứng",
        "category": "Đa dị ứng",
        "label": "[CROSS-02] Dị ứng đậu phộng + trứng — muốn ăn gỏi",
        "query": "Dị ứng đậu phộng và trứng, muốn ăn gỏi gà hoặc nộm bò",
        "profile": None,
        "expect_safe": ["đậu phộng", "lạc", "trứng", "mayonnaise"],
        "expect_warn": True,
        "notes": (
            "Gỏi gà/nộm bò thường có đậu phộng; gỏi Caesar hoặc nộm có mayonnaise. "
            "Conflict từ cả hai allergen. Kỳ vọng: warning mạnh, "
            "kết quả trả gỏi đặc biệt không có cả hai hoặc món thay thế tươi mát khác."
        ),
    },
    {
        "id": "CROSS-03",
        "allergy": "Giáp xác + Bệnh lý Tiểu đường",
        "category": "Dị ứng + bệnh lý",
        "label": "[CROSS-03] Dị ứng giáp xác + Tiểu đường type 2",
        "query": "Tôi bị tiểu đường và dị ứng tôm cua, muốn ăn trưa no mà không tăng đường",
        "profile": make_profile(
            allergies=["Dị ứng động vật giáp xác"],
            health_conditions=["Tiểu đường"],
        ),
        "expect_safe": ["tôm", "cua", "mắm tôm"],
        "expect_warn": False,
        "notes": (
            "Hai constraints khác loại: allergy (loại tôm/cua) + disease (loại tinh bột cao). "
            "Kỳ vọng: kết quả là cơm gạo lứt/rau xào/thịt luộc — không có tôm/cua, ít đường."
        ),
    },
    {
        "id": "CROSS-04",
        "allergy": "Thân mềm + Bệnh lý Gout",
        "category": "Dị ứng + bệnh lý",
        "label": "[CROSS-04] Dị ứng thân mềm + Gout — pool rất hẹp",
        "query": "Dị ứng mực ốc và bị Gout, muốn ăn gì",
        "profile": None,
        "expect_safe": ["mực", "ốc", "hàu", "nghêu"],
        "expect_warn": False,
        "notes": (
            "Gout: loại cứng tag 'Hải sản' + penalty đồ nội tạng, đồ đậm đà. "
            "Dị ứng thân mềm: loại mực/ốc/hàu. "
            "Hai lớp loại hải sản từ hai cơ chế khác nhau. "
            "Điểm thú vị: pool sau filter có thể rất nhỏ → kiểm tra expansion ở semantic pipeline."
        ),
    },
]


# ===========================================================================
# Tổng hợp tất cả test cases
# ===========================================================================

ALLERGY_TEST_CASES: list[dict] = (
    GIAC_XAC_CASES
    + THAN_MEM_CASES
    + DAU_PHONG_CASES
    + TRUNG_CASES
    + CROSS_CASES
)


# ---------------------------------------------------------------------------
# In tóm tắt khi chạy trực tiếp
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    by_allergy: dict[str, list[str]] = {}
    by_category: dict[str, int] = {}

    for tc in ALLERGY_TEST_CASES:
        by_allergy.setdefault(tc["allergy"], []).append(tc["id"])
        by_category[tc["category"]] = by_category.get(tc["category"], 0) + 1

    print(f"\n{'='*70}")
    print(f"  TỔNG SỐ TEST CASES: {len(ALLERGY_TEST_CASES)}")
    print(f"{'='*70}")

    print("\n📌 Phân bổ theo loại dị ứng:")
    for allergy, ids in by_allergy.items():
        print(f"  {allergy:<40} {len(ids):>3} cases  [{', '.join(ids)}]")

    print("\n📌 Phân bổ theo nhóm kịch bản:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat:<40} {count:>3} cases")

    print(f"\n{'='*70}")
    print("  Dùng trong compare_pipelines.py:")
    print("    from scripts.allergy_test_cases import ALLERGY_TEST_CASES")
    print("    TEST_CASES = ALLERGY_TEST_CASES")
    print(f"{'='*70}\n")
