"""
Phân loại ngữ cảnh ăn uống cho tên món ăn Việt Nam.

Mục đích: ngăn gợi ý địa điểm quán ăn cho những món thường được nấu tại nhà
(ví dụ: "Canh mướp nấu nấm", "Cháo gà hầm thuốc bắc").

Trả về một trong ba giá trị:
  "home_cooked"  — rất có khả năng là món nhà, không nên gợi ý quán ăn
  "restaurant"   — là món ăn ngoài hàng rõ ràng
  "both"         — không rõ hoặc có thể cả hai (mặc định — vẫn tìm quán bình thường)
"""
from __future__ import annotations

import re
import unicodedata


# ─── Normalisation (viết lại để không import vòng từ service.py) ─────────────

def _normalize(text: str) -> str:
    """Chuẩn hóa chuỗi: bỏ dấu tiếng Việt, chữ thường, giữ chữ cái và khoảng trắng."""
    nfd = unicodedata.normalize("NFD", text.strip().lower())
    no_marks = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return no_marks.replace("đ", "d")


# ─── Rule tables ─────────────────────────────────────────────────────────────

# Tiền tố tên món gần như luôn là món nhà (phải có dấu cách sau để tránh khớp sai).
# Kiểm tra RESTAURANT_OVERRIDES trước khi dùng danh sách này.
_HOME_PREFIXES: tuple[str, ...] = (
    "canh ",   # canh mướp, canh cải, canh chua, canh cà...
    "sup ",    # súp cua, súp gà, súp nấm...
    "chao ",   # cháo gà, cháo đậu xanh... (nhưng "cháo lòng", "cháo cá" có thể bán ngoài)
)

# Động từ chỉ phương pháp nấu xuất hiện BÊN TRONG tên món → miêu tả cách chế biến tại nhà.
# Dùng word boundary (\b) để tránh khớp sai (vd: "nhau", "chanh", "phở hầm").
# Lưu ý:
#   - "kho"  bị bỏ ra vì "Cá kho tộ", "Thịt kho" rất phổ biến ở quán ăn.
#   - "xao"  bị bỏ ra vì "Bò xào", "Rau xào" cũng có ở quán.
#   - "nuong" bị bỏ ra vì các món nướng thường có bán ngoài hàng.
_HOME_VERB_PATTERN = re.compile(r"\b(nau|ham)\b")
# "nau" ← nấu (canh mướp nấu nấm, cá nấu canh chua…)
# "ham" ← hầm (gà hầm thuốc bắc, sườn hầm khoai…)


# Các tên món / tiền tố tên món là đồ ăn ngoài hàng rõ ràng.
# Danh sách này được kiểm tra TRƯỚC _HOME_PREFIXES để tránh xung đột
# (vd: "Canh bún" bắt đầu bằng "canh " nhưng là đặc sản Huế bán ở quán).
_RESTAURANT_OVERRIDES: tuple[str, ...] = (
    "pho",          # phở
    "bun bo",       # bún bò Huế
    "bun cha",      # bún chả
    "bun rieu",     # bún riêu
    "bun mam",      # bún mắm
    "bun oc",       # bún ốc
    "banh mi",      # bánh mì
    "banh xeo",     # bánh xèo
    "banh can",     # bánh căn
    "banh cuon",    # bánh cuốn
    "banh canh",    # bánh canh
    "hu tieu",      # hủ tiếu
    "mi quang",     # mì Quảng
    "cao lau",      # cao lầu
    "com tam",      # cơm tấm
    "com ga",       # cơm gà
    "com hen",      # cơm hến (đặc sản Huế)
    "goi cuon",     # gỏi cuốn
    "cha gio",      # chả giò
    "nem ran",      # nem rán
    "nem cuon",     # nem cuốn
    "lau ",         # lẩu (kèm dấu cách để tránh khớp "lâu đời")
    "canh bun",     # canh bún — đặc sản Huế, bán ở quán
    "chao long",    # cháo lòng — quán ăn sáng
    "chao ca",      # cháo cá — thường bán ở quán
    "bun thit nuong",  # bún thịt nướng
    "bun moc",      # bún mọc
)


# ─── In-memory cache ─────────────────────────────────────────────────────────

_context_cache: dict[str, str] = {}


# ─── Classifier ──────────────────────────────────────────────────────────────

def classify_dining_context(dish: str) -> str:
    """
    Phân loại ngữ cảnh ăn của một tên món ăn Việt Nam.

    Dựa trên rule-based matching (không gọi API bên ngoài):
      1. Kiểm tra xem tên món có khớp với danh sách món ăn ngoài hàng không
         (restaurant overrides) → "restaurant"
      2. Kiểm tra tiền tố đặc trưng của món nhà (canh, súp, cháo...)
         → "home_cooked"
      3. Kiểm tra động từ chỉ phương pháp nấu xuất hiện trong tên
         (nấu, hầm) → "home_cooked"
      4. Không xác định được → "both" (mặc định, vẫn tìm quán bình thường)

    Parameters
    ----------
    dish : str
        Tên món ăn (tiếng Việt, có hoặc không có dấu).

    Returns
    -------
    str
        "home_cooked" | "restaurant" | "both"
    """
    if not dish or not dish.strip():
        return "both"

    cache_key = dish.strip().lower()
    if cache_key in _context_cache:
        return _context_cache[cache_key]

    # Thêm khoảng trắng cuối để prefix matching hoạt động đúng khi tên món
    # chỉ có một từ (ví dụ: "Cháo" thay vì "Cháo gà").
    normalized = _normalize(dish) + " "

    # ── Bước 1: Restaurant overrides — kiểm tra trước để xử lý ngoại lệ ──
    for keyword in _RESTAURANT_OVERRIDES:
        if normalized.startswith(keyword) or f" {keyword}" in normalized:
            result = "restaurant"
            _context_cache[cache_key] = result
            print(f"[DINING CTX] '{dish}' → restaurant (override: '{keyword}')")
            return result

    # ── Bước 2: Home-cooked prefixes ──
    for prefix in _HOME_PREFIXES:
        if normalized.startswith(prefix):
            result = "home_cooked"
            _context_cache[cache_key] = result
            print(f"[DINING CTX] '{dish}' → home_cooked (prefix: '{prefix.strip()}')")
            return result

    # ── Bước 3: Cooking verb mid-name ──
    if _HOME_VERB_PATTERN.search(normalized):
        result = "home_cooked"
        _context_cache[cache_key] = result
        print(f"[DINING CTX] '{dish}' → home_cooked (verb pattern)")
        return result

    # ── Bước 4: Không xác định ──
    result = "both"
    _context_cache[cache_key] = result
    return result
