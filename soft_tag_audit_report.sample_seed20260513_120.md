# Soft Tag Audit Report

- Tổng món audit: 120
- Món có cảnh báo: 47
- Tổng cảnh báo: 53

## Theo mức độ
- P0: 0
- P1: 9
- P2: 44

## Theo loại cảnh báo
- `core_not_grounded`: 24
- `hidden_seafood_in_ingredients`: 17
- `method_name_mismatch`: 6
- `healthy_conflict`: 3
- `rich_false_positive`: 2
- `spicy_false_positive`: 1

## Chi tiết

### #404 Pizza Xúc xích Ý
- Tags: Đậm đà, Món khô, Nướng, Béo ngậy, Hải sản, Từ sữa / Phô mai, Nhiều dầu mỡ / Calo cao, Giòn / Giòn rụm
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['sốt cà chua']

### #239 Khoai lang nướng
- Tags: Cay, Món khô, Kho/Rim, Giàu tinh bột, Mềm, Món Việt truyền thống, Ấm bụng
- P1 `method_name_mismatch`: Tên món gợi ý 'Nướng' nhưng tag hiện tại không có
- P1 `spicy_false_positive`: Có 'Cay' nhưng ớt/tiêu có thể chỉ là gia vị phụ

### #452 Mướp đắng kho tiêu chay
- Tags: Đậm đà, Nước sền sệt, Kho/Rim, Đắng, Mềm, Món Việt truyền thống, Món chay, Ăn trưa
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['nước tương']

### #266 Bánh tráng kẹp hành
- Tags: Đậm đà, Món khô, Chiên / Rán, Béo ngậy, Hải sản, Giàu đạm, Giòn / Giòn rụm, Mềm
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['dầu ăn']

### #96 Bún mắm tai mui
- Tags: Đậm đà, Món nước, Gỏi / Nộm / Trộn, Giàu đạm, Món Việt truyền thống
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['đậu phụ']

### #192 Trứng chiên thịt băm
- Tags: Đậm đà, Món khô, Chiên / Rán, Béo ngậy, Giàu đạm, Mềm, Món Việt truyền thống, Ăn no
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['nước mắm']

### #139 Cua rang me
- Tags: Đậm đà, Nước sền sệt, Rang, Chua, Hải sản, Giàu đạm, Món Việt truyền thống
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['dầu ăn']

### #400 Bánh Taco bò kiểu Mexico
- Tags: Đậm đà, Món khô, Gỏi / Nộm / Trộn, Chua, Hải sản, Giàu đạm, Giòn / Giòn rụm, Ăn trưa
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #136 Tôm hùm nướng phô mai
- Tags: Đậm đà, Món khô, Nướng, Béo ngậy, Hải sản, Từ sữa / Phô mai
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['phô mai bò cười', 'cream cheese', 'phô mai sợi']

### #333 Thịt nướng BBQ Hàn Quốc
- Tags: Đậm đà, Món khô, Nướng, Chua, Béo ngậy, Hải sản, Giàu đạm, Mềm
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #480 Nấm nướng giấy bạc chay
- Tags: Đậm đà, Món khô, Nướng, Béo ngậy, Giàu chất xơ, Healthy / Eat Clean, Mềm, Món chay
- P2 `healthy_conflict`: 'Healthy / Eat Clean' mâu thuẫn với tag dầu mỡ/béo/chế biến sẵn

### #51 Mì xào bò
- Tags: Đậm đà, Món khô, Xào, Giàu đạm, Giàu tinh bột, Mềm, Ẩm thực đường phố, Ăn trưa
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['thịt bò']

### #264 Gà rán sốt cay
- Tags: Đậm đà, Món khô, Chiên / Rán, Cay, Béo ngậy, Từ sữa / Phô mai, Giòn / Giòn rụm
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['bột chiên giòn']

### #420 Salad bơ tôm áp chảo
- Tags: Thanh đạm, Món khô, Gỏi / Nộm / Trộn, Béo ngậy, Hải sản, Giàu chất xơ, Giàu đạm, Healthy / Eat Clean
- P2 `healthy_conflict`: 'Healthy / Eat Clean' mâu thuẫn với tag dầu mỡ/béo/chế biến sẵn

### #423 Khoai tây múi cau nướng
- Tags: Đậm đà, Món khô, Kho/Rim, Cay, Hải sản, Giàu đạm, Mềm, Món Việt truyền thống
- P1 `method_name_mismatch`: Tên món gợi ý 'Nướng' nhưng tag hiện tại không có
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['xí muội băm', 'sa tế']

### #247 Xôi mặn
- Tags: Đậm đà, Món khô, Xào, Hải sản, Giàu đạm, Giàu tinh bột, Nhiều dầu mỡ / Calo cao, Mềm
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #114 Ốc hương xào bơ tỏi
- Tags: Đậm đà, Món khô, Xào, Béo ngậy, Hải sản, Giàu đạm, Dai / Sần sật, Ăn trưa
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['ớt sa tế']

### #382 Pizza Bò băm
- Tags: Đậm đà, Món khô, Nướng, Béo ngậy, Từ sữa / Phô mai, Giòn / Giòn rụm, Món Âu
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['sữa không đường']

### #103 Bún hến
- Tags: Đậm đà, Món khô, Xào, Hải sản, Giàu đạm, Món Việt truyền thống, Ăn trưa
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['nước mắm']

### #4 Mì Quảng Bò
- Tags: Đậm đà, Nước sền sệt, Rang, Hải sản, Giàu đạm, Đặc sản Đà Nẵng, Món Việt truyền thống
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #261 Bánh căn
- Tags: Đậm đà, Món khô, Chiên / Rán, Béo ngậy, Hải sản, Giàu đạm, Giòn / Giòn rụm, Món Việt truyền thống
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #419 Bò cuộn phô mai nướng
- Tags: Đậm đà, Món khô, Nướng, Béo ngậy, Từ sữa / Phô mai, Món Âu
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['thịt bò']

### #67 Bánh xèo miền Trung
- Tags: Đậm đà, Món khô, Chiên / Rán, Chua, Béo ngậy, Hải sản, Giàu đạm, Giòn / Giòn rụm
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['bột đậu nành', 'tương ớt Cholimex', 'nước mắm', 'bột ngọt', 'tiêu']

### #172 Cơm tấm sườn bì chả
- Tags: Đậm đà, Món khô, Nướng, Hải sản, Giàu đạm, Giàu tinh bột, Dai / Sần sật, Món Việt truyền thống
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #408 Salad Hy Lạp
- Tags: Béo ngậy, Món khô, Gỏi / Nộm / Trộn, Từ sữa / Phô mai, Giàu chất xơ, Healthy / Eat Clean, Thanh mát/Giải nhiệt, Món Âu
- P2 `healthy_conflict`: 'Healthy / Eat Clean' mâu thuẫn với tag dầu mỡ/béo/chế biến sẵn

### #68 Bánh xèo tôm nhảy
- Tags: Đậm đà, Món khô, Chiên / Rán, Béo ngậy, Hải sản, Giàu đạm, Giòn / Giòn rụm, Ẩm thực đường phố
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['dầu ăn']

### #345 Dimsum
- Tags: Đậm đà, Món khô, Chiên / Rán, Hấp / Luộc, Giàu đạm, Mềm, Món Á, Ăn vặt
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['dầu ăn']

### #95 Bún bắp bò gốc Huế
- Tags: Đậm đà, Món nước, Hầm / Ninh, Hải sản, Giàu đạm, Món Việt truyền thống, Ăn sáng
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #216 Cơm thịt heo rim mực
- Tags: Đậm đà, Món khô, Kho/Rim, Béo ngậy, Hải sản, Giàu đạm, Món Việt truyền thống, Ăn trưa
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['dầu ăn']

### #412 Bánh mì nướng kiểu Pháp
- Tags: Ngọt, Món khô, Chiên / Rán, Béo ngậy, Từ sữa / Phô mai, Giòn / Giòn rụm, Mềm, Món Việt truyền thống
- P1 `method_name_mismatch`: Tên món gợi ý 'Nướng' nhưng tag hiện tại không có

### #38 Phở xào giòn
- Tags: Đậm đà, Món khô, Chiên / Rán, Béo ngậy, Giàu đạm, Giàu tinh bột, Giòn / Giòn rụm, Ẩm thực đường phố
- P1 `method_name_mismatch`: Tên món gợi ý 'Xào' nhưng tag hiện tại không có

### #127 Mực sữa chiên nước mắm
- Tags: Đậm đà, Món khô, Kho/Rim, Hải sản, Giàu đạm, Món Việt truyền thống, Ăn no
- P1 `method_name_mismatch`: Tên món gợi ý 'Chiên / Rán' nhưng tag hiện tại không có

### #479 Đậu hũ sốt ngũ vị
- Tags: Đậm đà, Nước sền sệt, Kho/Rim, Béo ngậy, Giàu đạm, Giòn / Giòn rụm, Mềm, Món Việt truyền thống
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['dầu ăn']

### #346 Bánh bao kim sa
- Tags: Ngọt, Món khô, Hấp / Luộc, Béo ngậy, Bánh ngọt, Mềm, Ăn vặt
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['bột mì đa dụng', 'sữa tươi', 'sữa đặc']

### #263 Tokbokki lề đường
- Tags: Đậm đà, Món nước, Hầm / Ninh, Hải sản, Giàu đạm, Dai / Sần sật, Mềm, Ẩm thực đường phố
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #355 Miến xào Hàn Quốc
- Tags: Đậm đà, Món khô, Xào, Hải sản, Giàu đạm, Giàu tinh bột, Dai / Sần sật, Món Á
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #256 Khoai tây lốc xoáy
- Tags: Béo ngậy, Nước sền sệt, Kho/Rim, Nhiều dầu mỡ / Calo cao, Giòn / Giòn rụm, Ẩm thực đường phố, Món Việt truyền thống, Ăn vặt
- P1 `rich_false_positive`: Có 'Béo ngậy' nhưng chưa thấy nguyên liệu/cách nấu tạo độ béo rõ

### #59 Bánh canh xương chả
- Tags: Đậm đà, Món nước, Hầm / Ninh, Hải sản, Giàu đạm, Khó tiêu / Nặng bụng, Dai / Sần sật, Mềm
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #78 Bánh nậm
- Tags: Đậm đà, Món khô, Hấp / Luộc, Thanh đạm, Hải sản, Giàu đạm, Mềm, Ăn vặt
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #338 Bánh xèo Nhật Bản
- Tags: Đậm đà, Món khô, Chiên / Rán, Béo ngậy, Hải sản, Giàu đạm, Giòn / Giòn rụm, Ẩm thực đường phố
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #249 Bánh bao trứng muối
- Tags: Đậm đà, Món khô, Hấp / Luộc, Béo ngậy, Từ sữa / Phô mai, Giàu tinh bột, Mềm, Ẩm thực đường phố
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['thịt nạc xay']

### #321 Rau câu ngũ sắc
- Tags: Ngọt, Món nước, Hấp / Luộc, Béo ngậy, Hải sản, Từ sữa / Phô mai, Thanh mát/Giải nhiệt, Món lạnh
- P2 `hidden_seafood_in_ingredients`: Tên món không thể hiện hải sản nhưng ingredients có hải sản; cần review dữ liệu gốc

### #276 Khoai môn lệ phố
- Tags: Béo ngậy, Nước sền sệt, Kho/Rim, Giàu tinh bột, Giòn / Giòn rụm, Mềm, Món Việt truyền thống
- P1 `rich_false_positive`: Có 'Béo ngậy' nhưng chưa thấy nguyên liệu/cách nấu tạo độ béo rõ

### #165 Tu hài nướng mỡ hành
- Tags: Đậm đà, Món khô, Nướng, Béo ngậy, Giàu đạm, Dai / Sần sật, Mồi nhậu
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['màu điều', 'mì chính']

### #79 Bánh gói
- Tags: Ngọt, Món khô, Hấp / Luộc, Béo ngậy, Mềm, Món Việt truyền thống, Ăn vặt, Tráng miệng
- P1 `method_name_mismatch`: Tên món gợi ý 'Cuốn / Gói' nhưng tag hiện tại không có

### #294 Bánh chín tầng mây
- Tags: Ngọt, Món khô, Hấp / Luộc, Béo ngậy, Dai / Sần sật, Mềm, Món Việt truyền thống, Tráng miệng
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['nước màu xanh, đỏ, tím']

### #418 Pizza 4 loại phô mai
- Tags: Đậm đà, Món khô, Nướng, Béo ngậy, Từ sữa / Phô mai, Nhiều dầu mỡ / Calo cao, Món Âu
- P2 `core_not_grounded`: Core ingredient không xuất hiện trực tiếp trong source: ['đế pizza']
