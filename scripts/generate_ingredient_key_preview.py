"""Generate a dry-run ingredient key preview for review.

This script does not update the database and does not change search logic.
It reads the reviewed food JSON and tags_data.json, then writes a preview file
containing:
- alias_rules v1
- generated core_ingredient_keys per food
- audit hints for collision-sensitive keys

Example:
venv/bin/python scripts/generate_ingredient_key_preview.py --force
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_FOOD_INPUT = Path(
    "standard-data/ingredients-data/food-clean-categorized/"
    "raw_foods_enriched_labeled(final_488).categorized.clean.json"
)
DEFAULT_TAGS_INPUT = Path("standard-data/tags_data.json")
DEFAULT_OUTPUT = Path("standard-data/alias-rules/ingredient_key_preview.v1.json")


COLLISION_SENSITIVE_TOKENS = {"bo", "sua", "me", "ca", "nam", "dau", "gia", "oc", "cua", "tieu"}
PORK_CANONICAL_KEYS = {
    "canon:thit_heo",
    "canon:thit_heo_nac",
    "canon:noi_tang_heo",
    "canon:mo_heo",
    "canon:thit_heo_che_bien",
}
CHICKEN_CANONICAL_KEYS = {
    "canon:thit_ga",
    "canon:noi_tang_ga",
    "canon:thit_ga_che_bien",
}
DUCK_CANONICAL_KEYS = {
    "canon:thit_vit",
    "canon:thit_vit_che_bien",
}


def strip_accents(value: str) -> str:
    """Bỏ dấu tiếng Việt để tạo key máy đọc, ví dụ 'thăn bò' -> 'than bo'."""
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return value.replace("đ", "d").replace("Đ", "D")


def normalize_text_keep_accents(value: str) -> str:
    """
    Chuẩn hóa text nhưng vẫn giữ dấu để xử lý các cặp dễ nhầm.

    Hàm này dùng khi so alias có dấu, ví dụ phân biệt 'sữa' với 'sứa',
    'mè' với 'me', hoặc 'bơ' với 'bò'.
    """
    value = (value or "").lower()
    value = re.sub(r"[_\-/,.;:()\\[\\]{}]+", " ", value)
    value = re.sub(r"[^\w\sàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_base_key(value: str) -> str:
    """
    Tạo base key không dấu, snake_case cho mọi nguyên liệu.

    Đây là key trace/debug, không phải lúc nào cũng đủ an toàn để filter
    bệnh lý vì có collision như 'bơ'/'bò' cùng thành 'bo'.
    """
    value = strip_accents(value or "").lower()
    value = re.sub(r"[_\-/,.;:()\\[\\]{}]+", " ", value)
    value = re.sub(r"[^a-z0-9\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.replace(" ", "_")


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    """Loại trùng nhưng giữ nguyên thứ tự để output JSON ổn định, dễ review diff."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def phrase_in_spaced_text(text: str, phrase: str) -> bool:
    """Match cụm từ trên text có dấu bằng boundary để tránh dính vào từ dài hơn."""
    if not text or not phrase:
        return False
    pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
    return re.search(pattern, text) is not None


def phrase_in_key(base_key: str, alias_key: str) -> bool:
    """Match alias key theo token snake_case, ví dụ 'thit_bo' trong 'thit_bo_xay'."""
    if not base_key or not alias_key:
        return False
    return f"_{alias_key}_" in f"_{base_key}_"


def phrase_in_text_or_key(ingredient_text: str, base_key: str, phrase: str) -> bool:
    """Kiểm tra phrase trên cả text gốc và base_key không dấu để chặn collision ổn định."""
    if phrase_in_spaced_text(ingredient_text, phrase):
        return True
    phrase_key = normalize_base_key(phrase).replace("_", " ")
    base_key_text = base_key.replace("_", " ")
    return phrase_in_spaced_text(base_key_text, phrase_key)


def key_fallback_allowed(alias_key: str) -> bool:
    """
    Cho biết có được fallback sang match key không dấu hay không.

    Chỉ chặn các alias một token quá mơ hồ sau khi bỏ dấu như bo/sua/me/ca.
    Các alias nhiều token rõ nghĩa như ca_hoi, dau_hu, ca_chua vẫn được phép
    fallback để tags_data.json dạng không dấu có thể map đúng.
    """
    if alias_key in COLLISION_SENSITIVE_TOKENS:
        return False
    return True


def make_rule(
    canonical_key: str,
    aliases: list[str],
    group_keys: list[str],
    *,
    notes: str = "",
) -> dict:
    """
    Tạo một rule alias chuẩn.

    canonical_key đại diện nguyên liệu chuẩn cụ thể, còn group_keys là các nhóm
    y tế/dinh dưỡng rộng hơn để phục vụ filter sau này.
    """
    return {
        "canonical_key": canonical_key,
        "aliases": aliases,
        "alias_keys": dedupe_keep_order(normalize_base_key(alias) for alias in aliases),
        "group_keys": group_keys,
        "notes": notes,
    }


ALIAS_RULES: list[dict] = [
    make_rule(
        "canon:thit_bo",
        [
            "thịt bò",
            "bắp bò",
            "thăn bò",
            "gân bò",
            "gầu bò",
            "nạm bò",
            "sườn bò",
            "đuôi bò",
            "bò viên",
            "bò tái",
            "bò bắp",
            "bò xay",
            "bò băm",
            "bò phile",
            "bò phi lê",
            "ba chỉ bò",
            "thịt ba chỉ bò",
            "thịt ba chỉ bò mỹ",
            "giò me",
            "giò bê",
            "thịt bê",
            "phi lê bò",
            "thịt thăn bò",
            "thịt bắp bò",
            "thịt bò xay",
            "thịt bò băm",
            "thịt bò cắt mỏng",
            "thịt bò phile",
        ],
        ["group:thit_bo", "group:thit_do"],
        notes="Không map alias 'bò' trần để tránh nhầm với bơ.",
    ),
    make_rule(
        "canon:tom",
        [
            "tôm",
            "tôm sú",
            "tôm đất",
            "tôm khô",
            "tép khô",
            "tôm càng xanh",
            "tôm thẻ",
            "tôm hùm đất",
            "tôm chua",
            "tôm lột vỏ",
            "tôm mũ ni",
            "nõn tôm biển",
            "chạo tôm",
            "chả tôm",
            "ram tôm đất",
        ],
        ["group:giap_xac", "group:hai_san"],
    ),
    make_rule(
        "canon:cua_ghe",
        [
            "cua",
            "cua đồng",
            "cua biển",
            "cua gạch",
            "cua huỳnh đế",
            "cua thịt",
            "thịt cua biển",
            "ghẹ",
            "ghẹ xanh",
            "chả cua",
            "thanh cua",
            "riêu cua",
        ],
        ["group:giap_xac", "group:hai_san"],
    ),
    make_rule(
        "canon:be_be",
        ["bề bề", "bề bề bóc nõn", "tôm tít"],
        ["group:giap_xac", "group:hai_san"],
    ),
    make_rule(
        "canon:oc",
        [
            "ốc",
            "ốc hương",
            "ốc bươu",
            "ốc len",
            "ốc móng tay",
            "ốc bulot",
            "ốc giác",
            "ốc nhảy",
            "ốc hút",
        ],
        ["group:than_mem", "group:hai_san"],
    ),
    make_rule(
        "canon:ngheu_so_hau",
        [
            "nghêu",
            "nghêu hoa",
            "nghêu trắng",
            "ngao",
            "chip chip",
            "sò huyết",
            "sò dẹo",
            "sò lông",
            "sò lụa",
            "sò điệp",
            "hàu",
            "hàu sữa",
            "vẹm",
            "vẹm xanh",
            "tu hài",
            "bào ngư",
            "ruột hàu",
            "hến",
        ],
        ["group:than_mem", "group:hai_san"],
    ),
    make_rule(
        "canon:muc_bach_tuoc",
        [
            "mực",
            "mực ống",
            "mực baby",
            "mực nang",
            "mực trứng",
            "răng mực",
            "bạch tuộc",
            "khô mực",
        ],
        ["group:than_mem", "group:hai_san"],
    ),
    make_rule(
        "canon:sua_bien",
        ["sứa", "sứa ăn liền", "chân sứa"],
        ["group:hai_san"],
        notes="Accent-sensitive để không nhầm sứa với sữa.",
    ),
    make_rule(
        "canon:nhum",
        ["nhum"],
        ["group:hai_san"],
    ),
    make_rule(
        "canon:ca",
        [
            "cá basa",
            "cá bớp",
            "cá chìa vôi",
            "cá chẽm",
            "cá cơm",
            "cá cơm khô",
            "cá dìa đen",
            "cá diêu hồng",
            "cá đuối",
            "cá giò",
            "cá hanh",
            "cá hồi",
            "cá khô",
            "cá lóc",
            "cá mú",
            "cá nục",
            "cá ngừ",
            "cá phi lê",
            "cá rô đồng",
            "cá rô phi",
            "cá thu",
            "cá tráp",
            "cá trê",
            "cá trèn",
            "cá trích",
            "file cá lóc",
            "filet cá",
            "fillet cá",
            "phi lê cá",
            "chả cá",
            "chả cá nha trang",
            "cá viên",
            "đầu cá bớp",
            "vi cá",
        ],
        ["group:ca_co_vay", "group:hai_san"],
        notes="Không map alias 'cá' trần để tránh nhầm với cà chua/cà rốt.",
    ),
    make_rule(
        "canon:thit_heo",
        [
            "thịt heo",
            "thịt lợn",
            "thịt xay",
            "thịt băm",
            "thịt heo xay",
            "thịt heo băm",
            "thịt heo bằm",
            "heo xay",
            "thịt vai heo bằm",
            "lb thịt heo xay",
            "xương heo",
            "xương lợn",
            "xương ống heo",
            "xương sụn heo",
            "xương gà / heo",
            "nước dùng từ xương heo hoặc gà",
            "sườn heo",
            "sườn lợn",
            "lbs sườn heo non",
            "giò heo",
            "giò lợn",
            "bắp giò heo",
            "chân giò",
            "chân giò cắt khoanh",
            "cái giò heo trước",
            "khoanh giò heo hoặc cái đuôi heo",
            "thịt ba chỉ",
            "thịt ba chỉ hơi mỡ chút",
            "thịt ba chỉ luộc",
            "thịt ba chỉ heo",
            "thịt ba rọi",
            "thịt ba rọi heo",
            "thịt ba rọi heo luộc",
            "thịt ba rọi nhiều mỡ",
        ],
        ["group:thit_heo", "group:thit_do"],
    ),
    make_rule(
        "canon:thit_heo_nac",
        [
            "thịt nạc",
            "thịt heo nạc",
            "thịt lợn nạc",
            "thịt nạc băm",
            "thịt nạc xay",
            "thịt nạc vai",
            "thịt nạc dăm",
            "thịt heo nạc băm",
            "thịt nạc rang",
            "thịt nạc tùy khẩu phần ăn nhiều hay ít",
        ],
        ["group:thit_heo", "group:thit_do"],
    ),
    make_rule(
        "canon:thit_ga",
        [
            "gà",
            "gà ta",
            "gà ác",
            "thịt gà",
            "gà băm",
            "gà xay",
            "ức gà",
            "thịt ức gà",
            "ức gà lớn",
            "ức gà tươi",
            "cái ức gà",
            "đùi gà",
            "đùi gà góc tư",
            "cái đùi gà",
            "cánh gà",
            "chân gà",
            "chân gà rút xương",
            "thịt gà đùi băm / xay",
            "xương gà",
            "bộ xương gà",
            "nước dùng gà",
            "nước luộc gà",
            "xương gà / heo",
        ],
        ["group:thit_ga", "group:thit_trang"],
    ),
    make_rule(
        "canon:noi_tang_ga",
        [
            "bộ lòng gà",
            "bộ lòng gà : trứng non",
            "lòng gà",
            "tim gà",
            "mề gà",
        ],
        ["group:thit_ga", "group:thit_trang", "group:noitang"],
    ),
    make_rule(
        "canon:thit_ga_che_bien",
        [
            "gà quay",
            "gà xé",
        ],
        ["group:thit_ga", "group:thit_trang", "group:thit_che_bien_san"],
    ),
    make_rule(
        "canon:thit_vit",
        [
            "vịt",
            "thịt vịt",
            "đùi vịt",
            "cái đùi vịt góc tư",
            "cánh vịt",
            "ức vịt",
            "xương vịt",
            "vịt ko lấy đầu cổ cánh",
        ],
        ["group:thit_vit", "group:thit_trang"],
    ),
    make_rule(
        "canon:thit_vit_che_bien",
        [
            "vịt quay",
            "vịt xé",
        ],
        ["group:thit_vit", "group:thit_trang", "group:thit_che_bien_san"],
    ),
    make_rule(
        "canon:noitang",
        [
            "gan bò",
            "bao tử",
            "dồi",
            "dồi sụn",
            "huyết gà",
            "trứng vịt lộn",
            "hột vịt lộn",
            "trứng cút lộn",
            "hột cút lộn",
            "trứng non",
            "bánh huyết vịt",
        ],
        ["group:noitang"],
    ),
    make_rule(
        "canon:noi_tang_heo",
        [
            "gan heo",
            "gan lợn",
            "tim heo",
            "tim lợn",
            "lòng heo",
            "lòng lợn",
            "lòng già heo",
            "lòng heo : tim heo",
            "tai heo",
            "tai lợn",
            "mũi heo",
            "mũi lợn",
            "bộ óc heo",
            "óc heo",
            "óc lợn",
        ],
        ["group:thit_heo", "group:thit_do", "group:noitang"],
    ),
    make_rule(
        "canon:thit_che_bien_san",
        [
            "xúc xích",
            "lạp xưởng",
            "pate",
            "thịt hun khói",
            "chả lụa",
            "chả lụa chay",
            "bò viên",
            "cá viên",
            "thanh cua",
        ],
        ["group:thit_che_bien_san"],
    ),
    make_rule(
        "canon:mam_ruoc",
        ["mắm ruốc"],
        ["group:mam_len_men", "group:gia_vi_man_natri_cao", "group:hai_san"],
    ),
    make_rule(
        "canon:mam_tom",
        ["mắm tôm"],
        ["group:mam_len_men", "group:gia_vi_man_natri_cao", "group:hai_san"],
    ),
    make_rule(
        "canon:mam_nem",
        ["mắm nêm"],
        ["group:mam_len_men", "group:gia_vi_man_natri_cao", "group:hai_san"],
    ),
    make_rule(
        "canon:mam_tep",
        ["mắm tép"],
        ["group:mam_len_men", "group:gia_vi_man_natri_cao", "group:hai_san"],
    ),
    make_rule(
        "canon:mam_ca",
        ["mắm cá"],
        ["group:mam_len_men", "group:gia_vi_man_natri_cao", "group:hai_san"],
    ),
    make_rule(
        "canon:mam_len_men",
        [
            "mắm",
            "mắm ngon",
            "nước mắm",
            "nước mắm phú quốc",
            "nước mắm chua ngọt",
            "nước mắm tỏi ớt",
            "nước mắm loãng",
        ],
        ["group:mam_len_men", "group:gia_vi_man_natri_cao"],
    ),
    make_rule(
        "canon:gia_vi_man",
        [
            "muối",
            "bột canh",
            "chao",
            "kim chi",
            "dưa chua",
            "cà pháo",
            "xì dầu",
            "nước tương",
            "hắc xì dầu",
        ],
        ["group:gia_vi_man_natri_cao"],
    ),
    make_rule(
        "canon:muoi_tom",
        ["muối tôm", "muối tôm tây ninh", "muối tôm hành phi"],
        ["group:gia_vi_man_natri_cao"],
    ),
    make_rule(
        "canon:muoi_ot",
        ["muối ớt"],
        ["group:gia_vi_man_natri_cao", "group:cay_kich_ung"],
    ),
    make_rule(
        "canon:msg_phu_gia",
        [
            "bột ngọt",
            "mì chính",
            "hạt nêm",
            "hạt nêm chay",
            "hạt nêm hải sản",
            "bột nêm",
            "bột nêm chay",
        ],
        ["group:msg_phu_gia"],
    ),
    make_rule(
        "canon:dau_hao",
        ["dầu hào", "dầu hào chay"],
        ["group:gia_vi_man_natri_cao"],
    ),
    make_rule(
        "canon:sua",
        [
            "sữa",
            "sữa tươi",
            "sữa đặc",
            "sữa chua",
            "sữa bột",
            "sữa công thức",
            "sữa béo",
            "sữa không đường",
            "sữa tươi không đường",
            "sữa chua không đường",
        ],
        ["group:sua_va_che_pham_tu_sua"],
        notes="Accent-sensitive để không nhầm sữa với sứa.",
    ),
    make_rule(
        "canon:pho_mai",
        [
            "phô mai",
            "phomai",
            "pho mai",
            "mozzarella",
            "parmesan",
            "cream cheese",
            "whipping cream",
            "fresh cream",
            "mascarpone",
            "fromage",
            "sốt kem",
            "sốt caesar",
            "kem",
            "kem tươi",
            "kem vani",
            "kem đánh bông",
            "kem trứng",
        ],
        ["group:sua_va_che_pham_tu_sua"],
    ),
    make_rule(
        "canon:bo_sua",
        ["bơ lạt", "bơ mặn", "bơ nhạt", "bơ tường an", "butter"],
        ["group:sua_va_che_pham_tu_sua", "group:mo_dong_vat"],
        notes="Không map 'bơ' trần vì có thể là trái bơ.",
    ),
    make_rule(
        "canon:bo_thuc_vat",
        ["bơ thực vật"],
        [],
        notes="Tách riêng bơ thực vật, không gom vào thịt bò hoặc bơ sữa.",
    ),
    make_rule(
        "canon:trung",
        [
            "trứng",
            "trứng gà",
            "trứng gà ta",
            "trứng vịt",
            "trứng cút",
            "trứng muối",
            "lòng đỏ trứng",
            "lòng trắng trứng",
            "chả trứng",
            "mayonnaise",
            "mayonaise",
            "sốt mayonnaise",
            "sốt mayonaise",
            "bánh flan"
        ],
        ["group:trung"],
    ),
    make_rule(
        "canon:dau_nanh",
        [
            "đậu nành",
            "sữa đậu nành",
            "đậu hũ",
            "đậu hủ",
            "đậu phụ",
            "tàu hũ",
            "tàu hủ",
            "tàu hũ ky",
            "tàu hủ ky",
            "tempeh",
            "tương miso",
            "tàu xì",
            "nước tương",
            "xì dầu",
            "hắc xì dầu",
        ],
        ["group:dau_nanh"],
    ),
    make_rule(
        "canon:dau_phong",
        ["đậu phộng", "đậu phụng", "lạc", "bơ đậu phộng", "bơ lạc"],
        ["group:dau_phong"],
    ),
    make_rule(
        "canon:hat_cay",
        ["hạt điều", "hạt dẻ", "hạt óc chó", "óc chó", "hạnh nhân", "hạt thông"],
        ["group:hat_cay"],
    ),
    make_rule(
        "canon:me_vung",
        [
            "mè",
            "mè rang",
            "mè đen",
            "mè trắng",
            "mè vàng",
            "vừng",
            "vừng rang",
            "vừng đen",
            "vừng trắng",
            "dầu mè",
            "dầu vừng",
            "sốt mè rang",
            "nước sốt mè rang",
        ],
        ["group:me_vung"],
        notes="Accent-sensitive để không nhầm mè/vừng với me chua.",
    ),
    make_rule(
        "canon:gao",
        [
            "gạo",
            "gạo cũ loại nở xốp",
            "gạo dẻo",
            "gạo lứt",
            "gạo lứt đỏ",
            "gạo nếp",
            "gạo tấm",
            "cơm",
            "cơm gạo nhật",
            "cơm lứt trộn rong biển",
            "cơm nguội",
            "cơm nóng",
            "cơm nưa",
            "cơm nửa chén",
            "cơm tấm",
            "cơm trắng",
            "cơm nghệ",
            "cup gạo",
            "cup gạo tẻ",
            "lon gạo",
            "nắm gạo nếp",
            "bột gạo",
            "bột gạo nếp",
            "bột gạo tài kí",
            "bột gạo tẻ",
            "muỗngcanh bột gạo",
            "1m bột sắn/ bột gạo",
            "cái bánh tráng gạo",
            "bánh gạo topokki hanbe nhân phô mai",
        ],
        ["group:tinh_bot"],
    ),
    make_rule(
        "canon:bot_gao",
        [
            "gạo",
            "gạo cũ loại nở xốp",
            "gạo dẻo",
            "gạo lứt",
            "gạo lứt đỏ",
            "gạo nếp",
            "gạo tấm",
            "cơm",
            "cơm gạo nhật",
            "cơm lứt trộn rong biển",
            "cơm nguội",
            "cơm nóng",
            "cơm nưa",
            "cơm nửa chén",
            "cơm tấm",
            "cơm trắng",
            "cơm nghệ",
            "cup gạo",
            "cup gạo tẻ",
            "lon gạo",
            "nắm gạo nếp",
            "bột gạo",
            "bột gạo nếp",
            "bột gạo tài kí",
            "bột gạo tẻ",
            "muỗngcanh bột gạo",
            "1m bột sắn/ bột gạo",
            "cái bánh tráng gạo",
            "bánh gạo topokki hanbe nhân phô mai",
            "bún",
            "bún khô",
            "_70 bún khô",
            "gói bún khô",
            "bún gạo khô",
            "bún gạo lứt khô",
            "bún lứt",
            "bún tươi",
            "bún tươi dạng khô",
            "bún tươi sợi nhỏ",
            "kí bún lá tươi",
            "cân bún",
            "bánh phở",
            "bánh phở cắt sợi nhỏ vừa",
            "bánh phở tươi",
            "phở khô",
            "sợi phở khô",
            "sợi phở tươi",
            "vắt phở khô",
            "vắt phở khô gia lai",
            "mì quảng",
            "mì quảng tươi",
            "mì lá tươi",
            "vắt mì quảng dài đã luộc chín",
        ],
        ["group:tinh_bot"],
    ),
    make_rule(
        "canon:banh_mi",
        [
            "bánh mì",
            "bánh mì dài",
            "bánh mì đen",
            "bánh mì nóng giòn đặc ruột",
            "bánh mì sandwich",
            "chiếc bánh mì cỡ vừa vừa",
            "lát bánh mì ngũ cốc",
            "ổ bánh mì",
            "ổ bánh mì đặc ruột",
        ],
        ["group:tinh_bot"],
    ),
    make_rule(
        "canon:bot_mi",
        [
            "bột mì",
            "bột mì đa dụng",
            "bột mì ngang",
            "bột mì số",
            "bột tàn mì",
            "cup bột mì",
            "gói bột mì đa dụng",
            "bánh mì",
            "bánh mì dài",
            "bánh mì đen",
            "bánh mì nóng giòn đặc ruột",
            "bánh mì sandwich",
            "chiếc bánh mì cỡ vừa vừa",
            "lát bánh mì ngũ cốc",
            "ổ bánh mì",
            "ổ bánh mì đặc ruột",
            "bột bánh mì",
            "bánh sandwich",
            "mì ý",
            "mì ý hữu cơ",
            "mì trứng",
            "sợi mì trứng",
            "vắt mì trứng",
            "mì ramen",
            "gói mì ramen",
            "gói mì ramen sốt cay",
            "mì udon",
            "gói udon đông đá",
            "gói mì korea",
            "gói mì tuỳ chọn",
            "mì ăn kèm",
            "mì chiên giòn",
            "mì khoai tây tươi",
            "nắm tay mì sợi nhỏ của hàn",
            "vắt mì vàng",
            "vắt mì vàng cọng nhỏ khô",
            "hoành thánh",
            "hoành thánh lá",
            "lá hoành thánh",
            "sủi cảo",
            "bánh tortilla",
            "bột chiên giòn",
            "ngũ cốc"
        ],
        ["group:tinh_bot"],
        notes="Nhóm tinh bột có nguồn gốc chính từ bột mì/lúa mì.",
    ),
    make_rule(
        "canon:bun",
        [
            "bún",
            "bún khô",
            "_70 bún khô",
            "gói bún khô",
            "bún gạo khô",
            "bún gạo lứt khô",
            "bún lứt",
            "bún tươi",
            "bún tươi dạng khô",
            "bún tươi sợi nhỏ",
            "kí bún lá tươi",
            "cân bún",
        ],
        ["group:tinh_bot", "group:mon_soi"],
    ),
    make_rule(
        "canon:pho",
        [
            "bánh phở",
            "bánh phở cắt sợi nhỏ vừa",
            "bánh phở tươi",
            "phở khô",
            "sợi phở khô",
            "sợi phở tươi",
            "vắt phở khô",
            "vắt phở khô gia lai",
            "lá phở sắn",
        ],
        ["group:tinh_bot", "group:mon_soi"],
    ),
    make_rule(
        "canon:mi_quang",
        [
            "mì quảng",
            "mì quảng tươi",
            "mì lá tươi",
            "vắt mì quảng dài đã luộc chín",
        ],
        ["group:tinh_bot", "group:mon_soi"],
    ),
    make_rule(
        "canon:mi",
        [
            "mì ý",
            "mì ý hữu cơ",
            "mì trứng",
            "sợi mì trứng",
            "vắt mì trứng",
            "mì ramen",
            "gói mì ramen",
            "gói mì ramen sốt cay",
            "mì udon",
            "gói udon đông đá",
            "gói mì korea",
            "gói mì tuỳ chọn",
            "mì ăn kèm",
            "mì chiên giòn",
            "mì khoai tây tươi",
            "nắm tay mì sợi nhỏ của hàn",
            "vắt mì vàng",
            "vắt mì vàng cọng nhỏ khô",
        ],
        ["group:tinh_bot", "group:mon_soi"],
        notes="Không map alias 'mì' trần để tránh nhầm với mì Quảng và mì chính.",
    ),
    make_rule(
        "canon:mien",
        [
            "miến",
            "miến dong",
            "gói miến thái lan",
            "gói miến",
            "miến khoai lang hàn quốc",
            "miến rong",
            "miến đậu xanh",
            "miến (miến rong hoặc miến đậu xanh",
            "bún tàu",
        ],
        ["group:tinh_bot", "group:mon_soi"],
    ),
    make_rule(
        "canon:hu_tieu",
        [
            "hủ tiếu",
            "hủ tiếu khô",
        ],
        ["group:tinh_bot", "group:mon_soi"],
    ),
    make_rule(
        "canon:banh_canh",
        [
            "bánh canh",
            "bánh canh khô",
            "bánh canh bột gạo",
            "bánh canh bột lọc",
            "bánh canh gạo hoặc bánh canh xắt",
        ],
        ["group:tinh_bot", "group:mon_soi"],
    ),
    make_rule(
        "canon:cay_kich_ung",
        [
            "ớt",
            "ớt bột",
            "ớt xanh",
            "ớt hiểm",
            "ớt sa tế",
            "sa tế",
            "wasabi",
            "mù tạt",
        ],
        ["group:cay_kich_ung"],
    ),
    make_rule(
        "canon:sa_te_tom",
        ["sa tế tôm", "sa tế tôm tự làm"],
        ["group:gia_vi_man_natri_cao"],
    ),
    make_rule(
        "canon:tieu_gia_vi",
        ["tiêu", "tiêu xanh", "tiêu xay", "hạt tiêu"],
        ["group:gia_vi_thom"],
    ),
    make_rule(
        "canon:chua_kich_ung",
        [
            "chanh",
            "tắc",
            "quất",
            "giấm",
            "dấm",
            "khế",
            "xoài xanh",
            "me vắt",
            "me chín",
            "sốt me",
            "cốt me",
            "nước cốt me",
            "cà chua",
            "cà chua bi",
            "sốt cà chua",
            "tương cà",
            "ketchup"
        ],
        ["group:chua_kich_ung"],
        notes="Me chua tách khỏi mè/vừng bằng accent-sensitive matching.",
    ),
    make_rule(
        "canon:ruou_bia",
        ["bia", "rượu", "rượu trắng", "rượu vang", "rượu rum", "rượu sake"],
        ["group:ruou_bia"],
    ),
    make_rule(
        "canon:caffeine",
        ["cà phê", "cà phê đen", "cà phê hòa tan", "cacao", "socola", "chocolate"],
        ["group:caffeine"],
    ),
    make_rule(
        "canon:nuoc_ngot_co_ga",
        ["coca", "7up", "nước ngọt 7up", "nước ngọt có ga"],
        ["group:nuoc_ngot_co_ga", "group:duong_cao"],
    ),
    make_rule(
        "canon:nam",
        [
            "nấm",
            "nấm mèo",
            "mộc nhĩ",
            "nấm rơm",
            "nấm hương",
            "nấm đông cô",
            "nấm đùi gà",
            "nấm đùi gà baby",
            "nấm đùi gà to",
            "đầu nấm đùi gà to",
            "nấm kim châm",
            "nấm bào ngư",
            "nấm mỡ",
            "nấm linh chi",
            "nấm tuyết",
        ],
        ["group:nam"],
        notes="Accent-sensitive để không nhầm nấm với nạm.",
    ),
    make_rule(
        "canon:mang",
        ["măng", "măng chua", "măng tươi", "măng củ tươi"],
        ["group:mang"],
    ),
    make_rule(
        "canon:gia_do",
        ["giá", "giá đỗ", "giá sống", "giá trụng"],
        ["group:gia_do"],
        notes="Accent-sensitive để không nhầm giá với gia vị.",
    ),
    make_rule(
        "canon:mo_heo",
        [
            "mỡ heo",
            "mỡ lợn",
            "mỡ nước",
            "tóp mỡ",
            "da heo",
            "da lợn",
            "da heo quay",
            "da heo quay giòn",
            "bì heo",
            "thịt ba chỉ",
            "thịt ba chỉ hơi mỡ chút",
            "thịt ba chỉ luộc",
            "thịt ba rọi",
            "thịt ba rọi nhiều mỡ",
            "thịt mỡ",
            "shortening - mình dùng mỡ heo đã chiên để tủ lạnh cho đông",
        ],
        ["group:thit_heo", "group:thit_do", "group:mo_dong_vat"],
    ),
    make_rule(
        "canon:thit_heo_che_bien",
        [
            "giò sống",
            "heo quay",
            "lát thịt heo xông khói",
            "ruốc gà/ heo",
        ],
        ["group:thit_heo", "group:thit_do", "group:thit_che_bien_san"],
    ),
    make_rule(
        "canon:duong_cao",
        ["đường phèn", "caramel", "sữa đặc", "mật ong"],
        ["group:duong_cao"],
    ),
]


def alias_matches(ingredient: str, base_key: str, rule: dict) -> bool:
    """
    Kiểm tra một nguyên liệu có khớp alias rule hay không.

    Ưu tiên match bằng text có dấu để tránh collision. Chỉ fallback sang key
    không dấu khi alias thuộc nhóm ít rủi ro. Một vài ngoại lệ được chặn thủ công
    để không gán sai như 'thìa cà phê' thành caffeine, 'không đường' thành đường
    cao, hoặc 'ớt chuông' thành cay kích ứng.
    """
    ingredient_text = normalize_text_keep_accents(ingredient)
    for alias in rule["aliases"]:
        alias_key = normalize_base_key(alias)
        alias_text = normalize_text_keep_accents(alias)
        if rule["canonical_key"] == "canon:ngheu_so_hau":
            if alias_text == "bào ngư" and phrase_in_text_or_key(ingredient_text, base_key, "nấm bào ngư"):
                continue
        if rule["canonical_key"] == "canon:sua":
            if phrase_in_text_or_key(ingredient_text, base_key, "sữa đậu nành"):
                continue
        if rule["canonical_key"] == "canon:trung":
            if alias_text == "trứng" and phrase_in_text_or_key(ingredient_text, base_key, "mực trứng"):
                continue
            if alias_text == "trứng" and not (
                phrase_in_spaced_text(ingredient_text, alias_text) or base_key == alias_key
            ):
                continue
        if rule["canonical_key"] == "canon:me_vung":
            if any(
                phrase_in_spaced_text(ingredient_text, blocked)
                for blocked in ["sốt me", "nước sốt me", "mắm me"]
            ):
                continue
        if rule["canonical_key"] == "canon:noitang":
            if alias_key == "gan_bo" and "gân bò" in ingredient_text:
                continue
        if rule["canonical_key"] in PORK_CANONICAL_KEYS:
            if collision_token_present(base_key, "chay"):
                continue
            if alias_text in {
                "thịt ba chỉ",
                "thịt ba chỉ hơi mỡ chút",
                "thịt ba chỉ luộc",
                "thịt ba rọi",
                "thịt ba rọi nhiều mỡ",
            } and ("bò" in ingredient_text or collision_token_present(base_key, "bo")):
                continue
            if "group:noitang" in rule["group_keys"] and alias_text in {"tim heo", "tim lợn"}:
                if phrase_in_key(base_key, "hanh_tim"):
                    continue
        if rule["canonical_key"] == "canon:chua_kich_ung":
            if alias_text in {"me vắt", "me chín", "sốt me", "cốt me", "nước cốt me"}:
                if any(
                    phrase_in_spaced_text(ingredient_text, sesame_phrase)
                    for sesame_phrase in ["mè", "vừng", "sốt mè", "nước sốt mè"]
                ):
                    continue
            if alias_text in {"dấm", "giấm"} and not (
                phrase_in_spaced_text(ingredient_text, alias_text) or base_key == alias_key
            ):
                continue
        if rule["canonical_key"] in CHICKEN_CANONICAL_KEYS:
            if ingredient_text.startswith("trứng gà"):
                continue
            if "nấm đùi gà" in ingredient_text or "đầu nấm đùi gà" in ingredient_text:
                continue
            if alias_text == "gà":
                if any(phrase_in_spaced_text(ingredient_text, blocked) for blocked in ["gà quay", "gà xé"]):
                    continue
                if ingredient_text != "gà" and not ingredient_text.startswith("gà "):
                    continue
        if rule["canonical_key"] in DUCK_CANONICAL_KEYS:
            if ingredient_text.startswith("trứng vịt"):
                continue
            if alias_text == "vịt":
                if any(phrase_in_spaced_text(ingredient_text, blocked) for blocked in ["vịt quay", "vịt xé"]):
                    continue
                if ingredient_text != "vịt" and not ingredient_text.startswith("vịt "):
                    continue
        if rule["canonical_key"] in {"canon:gao", "canon:bot_gao"}:
            if alias_text == "gạo":
                if any(
                    phrase_in_text_or_key(ingredient_text, base_key, blocked)
                    for blocked in [
                        "giấm gạo",
                        "dấm gạo",
                        "nước vo gạo",
                        "bánh canh gạo",
                        "bánh canh bột gạo",
                    ]
                ):
                    continue
            if alias_text == "bột gạo":
                if phrase_in_text_or_key(ingredient_text, base_key, "bánh canh bột gạo"):
                    continue
            if alias_text.startswith("bún") or alias_text in {"kí bún lá tươi", "cân bún"}:
                if phrase_in_text_or_key(ingredient_text, base_key, "bún tàu"):
                    continue
            if alias_text == "cơm":
                if any(
                    phrase_in_text_or_key(ingredient_text, base_key, blocked)
                    for blocked in [
                        "ăn cơm",
                        "thìa ăn cơm",
                        "nước cơm",
                        "cơm dừa",
                        "trộn cơm",
                        "gia vị trộn cơm",
                        "hạt nêm cơm",
                        "cuộn cơm",
                    ]
                ):
                    continue
        if rule["canonical_key"] == "canon:bun":
            if phrase_in_text_or_key(ingredient_text, base_key, "bún tàu"):
                continue
            if phrase_in_text_or_key(ingredient_text, base_key, "gói gia vị") or phrase_in_text_or_key(
                ingredient_text, base_key, "ajiquick"
            ):
                continue
        if rule["canonical_key"] == "canon:pho":
            if any(
                phrase_in_text_or_key(ingredient_text, base_key, blocked)
                for blocked in ["gia vị phở", "nước tương trộn phở", "tương ăn phở", "viên nấu phở"]
            ):
                continue
        if rule["canonical_key"] == "canon:caffeine" and alias_text == "cà phê":
            if ingredient_text not in {"cà phê", "cafe", "coffee"}:
                continue
        if rule["canonical_key"] == "canon:duong_cao" and alias_text == "đường":
            if "không đường" in ingredient_text or "ko đường" in ingredient_text:
                continue
        if rule["canonical_key"] == "canon:cay_kich_ung" and alias_text == "ớt":
            if "ớt chuông" in ingredient_text:
                continue
        if phrase_in_spaced_text(ingredient_text, alias_text):
            return True
        if key_fallback_allowed(alias_key) and phrase_in_key(base_key, alias_key):
            return True
    return False


def generate_ingredient_keys(ingredient: str) -> tuple[list[str], list[str]]:
    """
    Sinh toàn bộ key cho một nguyên liệu.

    Mọi nguyên liệu luôn có base key. Nếu match alias rule thì thêm canon/group
    tương ứng. Hàm trả về cả danh sách key và rule đã match để debug.
    """
    base_key = normalize_base_key(ingredient)
    keys = [f"base:{base_key}"] if base_key else []
    matched_rules: list[str] = []

    for rule in ALIAS_RULES:
        if alias_matches(ingredient, base_key, rule):
            keys.append(rule["canonical_key"])
            keys.extend(rule["group_keys"])
            matched_rules.append(rule["canonical_key"])

    return dedupe_keep_order(keys), dedupe_keep_order(matched_rules)


def generate_food_key_preview(food: dict) -> dict:
    """
    Sinh preview key cho một món ăn từ danh sách core_ingredients.

    Output giữ lại ingredient_details để review từng nguyên liệu sinh ra key nào,
    đồng thời gom core_ingredient_keys ở cấp món để mô phỏng field DB tương lai.
    """
    all_keys: list[str] = []
    matched_rules: list[str] = []
    ingredient_details: list[dict] = []

    for ingredient in food.get("core_ingredients", []) or []:
        ingredient_keys, ingredient_rules = generate_ingredient_keys(ingredient)
        all_keys.extend(ingredient_keys)
        matched_rules.extend(ingredient_rules)
        ingredient_details.append(
            {
                "ingredient": ingredient,
                "base_key": f"base:{normalize_base_key(ingredient)}",
                "keys": ingredient_keys,
                "matched_rules": ingredient_rules,
            }
        )

    core_ingredient_keys = dedupe_keep_order(all_keys)
    matched_rules = dedupe_keep_order(matched_rules)
    unmapped_base_keys = [
        detail["base_key"]
        for detail in ingredient_details
        if detail["base_key"] and not detail["matched_rules"]
    ]

    return {
        "name": food.get("name", ""),
        "soft_tags": food.get("soft_tags", []) or [],
        "taste_profile": food.get("taste_profile", []) or [],
        "meal_context": food.get("meal_context", []) or [],
        "occasion_context": food.get("occasion_context", []) or [],
        "core_ingredients": food.get("core_ingredients", []) or [],
        "core_ingredient_keys": core_ingredient_keys,
        "matched_rules": matched_rules,
        "unmapped_base_keys": dedupe_keep_order(unmapped_base_keys),
        "ingredient_details": ingredient_details,
    }


def collision_token_present(base_key: str, token: str) -> bool:
    """Kiểm tra token nhạy cảm có xuất hiện độc lập trong base key hay không."""
    return token in base_key.replace("base:", "").split("_")


def build_collision_summary(food_previews: list[dict]) -> dict:
    """
    Tạo báo cáo các base key có token dễ collision.

    Phần này giúp review các bẫy như bo/sua/me/ca/nam/dau/gia trong dữ liệu thật,
    thay vì âm thầm để rule bỏ dấu quyết định sai.
    """
    summary: dict[str, list[dict]] = {}
    buckets: dict[str, dict[str, dict]] = {
        token: defaultdict(lambda: {"count": 0, "examples": []})
        for token in COLLISION_SENSITIVE_TOKENS
    }

    for food in food_previews:
        for detail in food["ingredient_details"]:
            base_key = detail["base_key"]
            for token in COLLISION_SENSITIVE_TOKENS:
                if collision_token_present(base_key, token):
                    entry = buckets[token][base_key]
                    entry["count"] += 1
                    if len(entry["examples"]) < 8:
                        entry["examples"].append(
                            {
                                "food": food["name"],
                                "ingredient": detail["ingredient"],
                                "keys": detail["keys"],
                            }
                        )

    for token, token_bucket in buckets.items():
        rows = []
        for base_key, data in token_bucket.items():
            rows.append(
                {
                    "base_key": base_key,
                    "count": data["count"],
                    "examples": data["examples"],
                }
            )
        summary[f"base:{token}"] = sorted(
            rows,
            key=lambda row: (-row["count"], row["base_key"]),
        )

    return summary


def add_expected_group_issue(
    issues: list[dict],
    food: dict,
    expected_key: str,
    reason: str,
) -> None:
    """Thêm một issue audit nếu món thiếu key kỳ vọng."""
    if expected_key not in food["core_ingredient_keys"]:
        issues.append(
            {
                "name": food["name"],
                "expected_key": expected_key,
                "reason": reason,
                "core_ingredients": food["core_ingredients"],
                "core_ingredient_keys": food["core_ingredient_keys"],
            }
        )


def build_missing_expected_group(food_previews: list[dict]) -> list[dict]:
    """
    Tìm các món có tín hiệu rõ nhưng chưa sinh được group/canon kỳ vọng.

    Đây là audit heuristic, không sửa dữ liệu. Ví dụ món có soft_tag Hải sản
    nhưng thiếu group:hai_san sẽ được đưa vào danh sách review.
    """
    issues: list[dict] = []

    for food in food_previews:
        normalized_values = [normalize_base_key(food["name"])]
        normalized_values.extend(
            detail["base_key"].removeprefix("base:")
            for detail in food["ingredient_details"]
        )
        accent_text_values = [normalize_text_keep_accents(food["name"])]
        accent_text_values.extend(
            normalize_text_keep_accents(detail["ingredient"])
            for detail in food["ingredient_details"]
        )
        soft_tags = set(food.get("soft_tags", []) or [])

        if "Hải sản" in soft_tags:
            add_expected_group_issue(
                issues,
                food,
                "group:hai_san",
                "soft_tag Hải sản nhưng thiếu group:hai_san",
            )

        beef_signals = [
            "thit_bo",
            "bap_bo",
            "than_bo",
            "gan_bo",
            "gau_bo",
            "nam_bo",
            "suon_bo",
            "duoi_bo",
            "bo_vien",
        ]
        if any(
            phrase_in_key(normalized, signal)
            for normalized in normalized_values
            for signal in beef_signals
        ):
            add_expected_group_issue(
                issues,
                food,
                "canon:thit_bo",
                "có tín hiệu thịt bò nhưng thiếu canon:thit_bo",
            )

        salty_signals = [
            "nuoc_mam",
            "mam_tom",
            "mam_ruoc",
            "mam_nem",
            "muoi",
            "hat_nem",
            "bot_canh",
        ]
        has_salty_signal = any(
            phrase_in_key(normalized, signal)
            for normalized in normalized_values
            for signal in salty_signals
        )
        # Chỉ xem "chao" là gia vị mặn khi text gốc thật sự là "chao".
        # Không dùng base_key không dấu ở đây vì "cháo"/"chảo" cũng thành "chao".
        has_salty_chao_signal = any(
            phrase_in_spaced_text(text, "chao")
            for text in accent_text_values
        )
        if has_salty_signal or has_salty_chao_signal:
            add_expected_group_issue(
                issues,
                food,
                "group:gia_vi_man_natri_cao",
                "có tín hiệu mắm/muối/chao nhưng thiếu group:gia_vi_man_natri_cao",
            )

    return issues


def build_alias_rule_coverage(tags_data: list[dict]) -> dict:
    """
    Đo mức độ alias_rules phủ được nguyên liệu trong tags_data.json.

    Mục tiêu là biết exclude_ingredient/prefer_ingredient nào đã map được sang
    canon/group và cái nào còn unmapped để tiếp tục mở rộng rule.
    """
    exclude_values = sorted({value for tag in tags_data for value in tag.get("exclude_ingredient", []) or []})
    prefer_values = sorted({value for tag in tags_data for value in tag.get("prefer_ingredient", []) or []})

    def map_values(values: list[str]) -> dict:
        """Map một danh sách ingredient rule sang key và tách mapped/unmapped."""
        mapped: list[dict] = []
        unmapped: list[str] = []
        for value in values:
            base_key = normalize_base_key(value)
            keys, rules = generate_ingredient_keys(value)
            if rules:
                mapped.append({"ingredient": value, "keys": keys, "matched_rules": rules})
            else:
                unmapped.append(value)
        return {
            "total": len(values),
            "mapped": len(mapped),
            "unmapped": len(unmapped),
            "mapped_examples": mapped[:80],
            "unmapped_examples": unmapped[:120],
        }

    return {
        "exclude_ingredient": map_values(exclude_values),
        "prefer_ingredient": map_values(prefer_values),
    }


def build_stats(food_previews: list[dict]) -> dict:
    """Tổng hợp thống kê nhanh cho preview output."""
    key_counter = Counter()
    rule_counter = Counter()
    for food in food_previews:
        key_counter.update(food["core_ingredient_keys"])
        rule_counter.update(food["matched_rules"])

    return {
        "unique_core_ingredient_keys": len(key_counter),
        "foods_with_any_matched_rule": sum(1 for food in food_previews if food["matched_rules"]),
        "top_core_ingredient_keys": [
            {"key": key, "count": count}
            for key, count in key_counter.most_common(80)
        ],
        "matched_rule_counts": [
            {"rule": rule, "count": count}
            for rule, count in rule_counter.most_common()
        ],
    }


def main() -> None:
    """CLI entrypoint: đọc input JSON, sinh preview, ghi output và in summary."""
    parser = argparse.ArgumentParser(description="Generate ingredient key preview JSON.")
    parser.add_argument("--foods", default=str(DEFAULT_FOOD_INPUT), help="Reviewed food JSON input")
    parser.add_argument("--tags", default=str(DEFAULT_TAGS_INPUT), help="tags_data.json input")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Preview JSON output")
    parser.add_argument("--force", action="store_true", help="Overwrite output if it already exists")
    args = parser.parse_args()

    food_path = Path(args.foods)
    tags_path = Path(args.tags)
    output_path = Path(args.output)

    if not food_path.exists():
        raise FileNotFoundError(f"Food input not found: {food_path}")
    if not tags_path.exists():
        raise FileNotFoundError(f"Tags input not found: {tags_path}")
    if output_path.exists() and not args.force:
        raise FileExistsError(f"Output already exists, use --force to overwrite: {output_path}")

    foods_data = json.loads(food_path.read_text(encoding="utf-8"))
    tags_data = json.loads(tags_path.read_text(encoding="utf-8"))

    food_previews = [generate_food_key_preview(food) for food in foods_data]

    output = {
        "metadata": {
            "source_food_file": str(food_path),
            "source_tags_file": str(tags_path),
            "foods_count": len(foods_data),
            "tags_count": len(tags_data),
            "note": "Dry-run preview only. Does not update DB or backend search logic.",
        },
        "alias_rules": ALIAS_RULES,
        "food_key_preview": food_previews,
        "audit_summary": {
            "stats": build_stats(food_previews),
            "alias_rule_coverage_from_tags_data": build_alias_rule_coverage(tags_data),
            "collision_sensitive_base_keys": build_collision_summary(food_previews),
            "foods_missing_expected_group": build_missing_expected_group(food_previews),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    stats = output["audit_summary"]["stats"]
    coverage = output["audit_summary"]["alias_rule_coverage_from_tags_data"]
    print(f"Output: {output_path}")
    print(f"Foods: {len(foods_data)}")
    print(f"Alias rules: {len(ALIAS_RULES)}")
    print(f"Unique core_ingredient_keys: {stats['unique_core_ingredient_keys']}")
    print(f"Foods with any matched rule: {stats['foods_with_any_matched_rule']}")
    print(
        "Tags exclude mapped/unmapped: "
        f"{coverage['exclude_ingredient']['mapped']}/"
        f"{coverage['exclude_ingredient']['unmapped']}"
    )
    print(
        "Foods missing expected group: "
        f"{len(output['audit_summary']['foods_missing_expected_group'])}"
    )


if __name__ == "__main__":
    main()
