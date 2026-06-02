# Các lệnh thường dùng

**URL production:** https://food-ai-backend-497531627370.asia-southeast1.run.app  
**Thư mục chạy lệnh:** `/backend`

---

## Chạy ở LOCAL (khi đang lập trình)

```bash
# Kích hoạt môi trường ảo (bắt buộc mỗi lần mở terminal mới)
source venv/bin/activate

# Chạy server local với hot reload (tự động reload khi sửa code)
uvicorn app.main:app --reload --port 8000
```

- Swagger UI: http://localhost:8000/docs
- Yêu cầu PostgreSQL đang chạy ở local và file `.env` đúng
- Khi sửa code, server tự reload — không cần restart thủ công

---

## Deploy lên CLOUD (khi muốn cập nhật production)

```bash
# Sửa code → build + deploy lên Google Cloud (~5 phút)
./deploy.sh

# Sửa tags_data.json → build + deploy + sync tags tự động
./deploy.sh --sync-tags

# Chỉ deploy lại không build (khi chỉ đổi config, nhanh hơn)
./deploy.sh --no-build
```

---

## Sync dữ liệu món ăn lên Cloud (foods JSON)

```bash
# Bước 1 — Terminal 1: mở proxy kết nối Cloud SQL (giữ chạy, đừng tắt)
cloud-sql-proxy $(gcloud config get-value project):asia-southeast1:food-ai-db --port=5433

# Bước 2 — Terminal 2: chạy sync
DB_HOST=127.0.0.1 DB_PORT=5433 DB_USERNAME=app_user \
DB_PASSWORD="<password>" DB_NAME=food_ai_db \
python -m app.db.seed --foods
```

---

## Xem logs production khi có lỗi

```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=food-ai-backend" \
  --limit=30 --format="table(timestamp,textPayload)" \
  --project=$(gcloud config get-value project)
```

---

## Cloud SQL Studio (quản lý database production)

Vào: https://console.cloud.google.com/sql/instances/food-ai-db/studio  
- Database: `food_ai_db`  
- User: `app_user` (thao tác dữ liệu) hoặc `postgres` (sửa schema/quyền)

---

## Trạng thái service production

```bash
gcloud run services describe food-ai-backend --region=asia-southeast1
```
