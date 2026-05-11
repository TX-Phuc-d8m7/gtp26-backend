import json

# Đường dẫn tới file JSON của bạn
file_path = "unique_ingredients.json"

try:
    # Mở và đọc file
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)
        
    # Trích xuất mảng tên nguyên liệu
    ingredient_names = [item.get("ingredient") for item in data if "ingredient" in item]
    
    # In ra kết quả
    print(json.dumps(ingredient_names, ensure_ascii=False, indent=4))
    
    # (Tuỳ chọn) Nếu bạn muốn lưu danh sách này ra một file mới
    with open("unique_ingredient_names_only.json", "w", encoding="utf-8") as out_file:
        json.dump(ingredient_names, out_file, ensure_ascii=False, indent=4)
        print("\n✅ Đã lưu kết quả ra file ingredient_names_only.json")

except FileNotFoundError:
    print(f"❌ Không tìm thấy file {file_path}")