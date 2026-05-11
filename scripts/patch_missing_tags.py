import json
import os

def patch_tags():
    input_file = "foods_enriched_v2.json"
    
    if not os.path.exists(input_file):
        print(f"Không tìm thấy file {input_file}")
        return

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            foods = json.load(f)
    except Exception as e:
        print(f"Error loading {input_file}: {e}")
        return

    updated_count = 0
    for food in foods:
        name_lower = food.get("name", "").lower()
        tags = food.get("soft_tags", [])
        original_tags = tags.copy()
        
        # Hấp / Luộc
        if "hấp" in name_lower or "luộc" in name_lower:
            if "Hấp / Luộc" not in tags:
                tags.append("Hấp / Luộc")
                
        # Nướng
        if "nướng" in name_lower or "quay" in name_lower:
            if "Nướng" not in tags:
                tags.append("Nướng")
                
        # Chiên / Rán
        if "chiên" in name_lower or "rán" in name_lower:
            if "Chiên / Rán" not in tags:
                tags.append("Chiên / Rán")
                
        # Xào
        if "xào" in name_lower:
            if "Xào" not in tags:
                tags.append("Xào")
                
        # Kho / Rim
        if "kho " in name_lower or " rim" in name_lower or name_lower.startswith("kho "):
            if "Kho/Rim" not in tags:
                tags.append("Kho/Rim")

        # Lẩu
        if "lẩu" in name_lower:
            if "Lẩu" not in tags:
                tags.append("Lẩu")
                
        if set(tags) != set(original_tags):
            food["soft_tags"] = tags
            updated_count += 1
            new_tags = set(tags) - set(original_tags)
            print(f"✅ Đã bổ sung {list(new_tags)} cho món: {food['name']}")

    if updated_count > 0:
        with open(input_file, "w", encoding="utf-8") as f:
            json.dump(foods, f, ensure_ascii=False, indent=2)
        print(f"\n🎉 Đã cập nhật thành công {updated_count} món ăn trong {input_file}")
    else:
        print("\n✨ Không có món nào cần cập nhật thêm.")

if __name__ == "__main__":
    patch_tags()
