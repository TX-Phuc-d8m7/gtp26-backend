# Kinh nghiệm Deploy Backend lên Google Cloud Run

## Tổng quan quy trình

```
Code (local) → Docker Image (Cloud Build) → Cloud Run (chạy app) → Cloud SQL (database)
```

---

## Các lỗi đã gặp và cách giải quyết

---

### Lỗi 1: Python version không khớp với thư viện

**Triệu chứng:**
```
ERROR: numpy==2.4.6 requires Python >=3.11
```

**Nguyên nhân:** Dockerfile dùng `python:3.10-slim` nhưng một số package yêu cầu Python 3.11+.

**Giải quyết:** Đổi base image trong Dockerfile:
```dockerfile
FROM python:3.11-slim   # thay vì python:3.10-slim
```

**Phòng tránh:** Luôn kiểm tra phiên bản Python trong `venv` local rồi dùng đúng phiên bản đó trong Dockerfile:
```bash
python --version   # xem local đang dùng version nào
```

---

### Lỗi 2: Thiếu package trong `requirements.txt`

**Triệu chứng (xảy ra nhiều lần, mỗi lần một module):**
```
ModuleNotFoundError: No module named 'asyncpg'
ModuleNotFoundError: No module named 'uvicorn'
ImportError: email-validator is not installed
```

**Nguyên nhân:** `requirements.txt` không đầy đủ — một số package được cài trực tiếp vào `venv` mà không được thêm vào file.

**Giải quyết:** Thêm từng package còn thiếu vào `requirements.txt` sau mỗi lần gặp lỗi.

**Phòng tránh lần sau:** Trước khi deploy lần đầu, sinh `requirements.txt` từ `venv` đang chạy được:
```bash
pip freeze > requirements.txt
```
Sau đó xem lại và xóa những package không liên quan đến app (langchain, jupyter...).

Hoặc test build Docker ở local trước:
```bash
docker build -t backend-test .
docker run --rm backend-test python -c "from app.main import app; print('OK')"
```

---

### Lỗi 3: App import từ thư mục bị loại khỏi Docker image

**Triệu chứng:**
```
ModuleNotFoundError: No module named 'scripts'
```

**Nguyên nhân:** File `.dockerignore` loại `scripts/` ra khỏi image, nhưng `app/modules/ingredients/service.py` lại import từ `scripts/generate_ingredient_key_preview.py` ở module level (dòng đầu file).

**Giải quyết:** Xóa `scripts/` khỏi `.dockerignore`.

**Bài học:** Thư mục tên là `scripts/` không có nghĩa là chỉ dùng offline. Phải kiểm tra xem app có import gì từ đó không:
```bash
grep -rn "from scripts" app/
grep -rn "import scripts" app/
```

---

### Lỗi 4: File data bị loại khỏi Docker image nhưng được load lúc khởi động

**Triệu chứng:**
```
FileNotFoundError: /app/standard-data/generated-rules/medical-advice-rules/medical_advice_rules.json
```

**Nguyên nhân:** `.dockerignore` loại toàn bộ `standard-data/generated-rules/` ra, nhưng `explanation.py` và `validation.py` đọc file này **ngay khi import** (module level), không phải lúc gọi hàm.

**Giải quyết:** Chỉ loại những thư mục thực sự không cần:
```
# .dockerignore — chỉ loại dữ liệu nặng không dùng lúc runtime
standard-data/ingredients-data/
standard-data/generated-rules/individual/
standard-data/alias-rules/
standard-data/testing_data/
standard-data/dining-context/
```
Giữ lại `medical-advice-rules/`, `tags_data.json` vì được dùng lúc app khởi động.

**Phòng tránh lần sau:** Trước khi thêm vào `.dockerignore`, chạy lệnh này để biết file nào được đọc từ `standard-data/`:
```bash
grep -rn "standard-data\|STANDARD_DATA_DIR" app/ | grep -v "__pycache__"
```
Phân biệt 2 loại:
- **Module-level load** (đọc khi import) → app crash ngay khi khởi động nếu thiếu file
- **Function-level load** (đọc khi gọi hàm) → app khởi động được, chỉ crash khi dùng tính năng đó

---

### Lỗi 5: Password có ký tự đặc biệt trong connection string

**Triệu chứng:**
```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "app_user"
```

**Nguyên nhân:** Password chứa ký tự `@`. Khi nhúng vào URL `postgresql+asyncpg://user:pass@word@/db`, SQLAlchemy parse sai — cắt password tại ký tự `@` đầu tiên.

**Giải quyết:** URL-encode password trong `config.py`:
```python
from urllib.parse import quote_plus

encoded_password = quote_plus(self.db_password)
return f"postgresql+asyncpg://{self.db_username}:{encoded_password}@/{self.db_name}?host={self.db_host}"
```

**Phòng tránh lần sau:** Luôn URL-encode password khi build connection string thủ công. Hoặc đặt password không chứa ký tự đặc biệt (`@`, `#`, `%`, `&`).

---

### Lỗi 6: `app_user` không có quyền ALTER TABLE

**Triệu chứng:**
```
asyncpg.exceptions.InsufficientPrivilegeError: must be owner of table foods
ALTER TABLE foods ADD COLUMN IF NOT EXISTS taste_profile ...
```

**Nguyên nhân:** Database được import bằng user `postgres` (superuser), nên tất cả bảng do `postgres` sở hữu. `app_user` là user thường, không thể ALTER bảng người khác tạo.

**Giải quyết:** Chuyển ownership toàn bộ bảng sang `app_user` trong Cloud SQL Studio (chạy với user `postgres`):
```sql
ALTER TABLE foods OWNER TO app_user;
ALTER TABLE tags OWNER TO app_user;
ALTER TABLE users OWNER TO app_user;
ALTER TABLE query_logs OWNER TO app_user;
ALTER TABLE user_health_profiles OWNER TO app_user;
ALTER TABLE favorite_foods OWNER TO app_user;
ALTER TABLE chat_threads OWNER TO app_user;
ALTER TABLE chat_messages OWNER TO app_user;
ALTER TABLE food_recommendation_feedbacks OWNER TO app_user;
GRANT ALL PRIVILEGES ON SCHEMA public TO app_user;
```

**Phòng tránh lần sau:** Khi import database, import bằng đúng user sẽ chạy app:
```bash
psql -h 127.0.0.1 -U app_user -d food_ai_db < backup.sql
```
Hoặc ngay sau khi import, chạy lệnh OWNER TO bên trên.

---

### Lỗi 7: Thiếu IAM permissions cho Cloud Run và Cloud Build

**Triệu chứng (nhiều lỗi 403 khác nhau):**
```
# Cloud Build không upload được source
ERROR 403: Access denied to Cloud Storage

# Cloud Build không push được image
ERROR 403: Access denied to Artifact Registry

# Cloud Run không đọc được secrets
ERROR: Secret Manager access denied

# Cloud Run không kết nối được Cloud SQL
ConnectionRefusedError: Connection refused (Unix socket)
```

**Giải quyết:** Cấp đủ roles cho 2 service account:

```bash
PROJECT=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

# Cloud Build cần
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$CLOUDBUILD_SA" --role="roles/storage.admin"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$CLOUDBUILD_SA" --role="roles/artifactregistry.writer"

# Cloud Run cần
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$COMPUTE_SA" --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$COMPUTE_SA" --role="roles/cloudsql.client"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$COMPUTE_SA" --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$COMPUTE_SA" --role="roles/storage.objectAdmin"
```

**Phòng tránh lần sau:** Chạy tất cả lệnh IAM này trước khi deploy lần đầu.

---

## Checklist trước khi deploy lần đầu

```
[ ] Dockerfile dùng đúng Python version (kiểm tra bằng `python --version` ở local)
[ ] requirements.txt đầy đủ (chạy `pip freeze` từ venv đang hoạt động)
[ ] Kiểm tra .dockerignore không loại nhầm file cần thiết:
    - grep xem app có import gì từ thư mục sẽ loại không
    - grep xem app có đọc file data nào lúc module-level không
[ ] Cấp đủ IAM roles cho Cloud Build SA và Cloud Run SA
[ ] Password không chứa ký tự đặc biệt, hoặc code đã URL-encode
[ ] Sau khi import database, chuyển ownership sang app_user
```

---

## Checklist khi gặp lỗi container không start

```
1. Xem logs ngay sau khi deploy fail:
   gcloud logging read \
     "resource.type=cloud_run_revision AND resource.labels.revision_name=<REVISION>" \
     --limit=50 --format="table(timestamp,textPayload)" \
     --project=$(gcloud config get-value project)

2. Đọc error message cuối cùng trong log — thường rất rõ ràng

3. Các lỗi thường gặp và hướng xử lý:
   - ModuleNotFoundError   → thêm package vào requirements.txt, rebuild
   - FileNotFoundError     → kiểm tra .dockerignore, rebuild
   - InvalidPasswordError  → kiểm tra URL encoding của password
   - InsufficientPrivilege → cấp quyền hoặc chuyển ownership bảng
   - Connection refused    → kiểm tra IAM cloudsql.client, cloud SQL instance name
   - Access denied 403     → cấp IAM roles còn thiếu
```
