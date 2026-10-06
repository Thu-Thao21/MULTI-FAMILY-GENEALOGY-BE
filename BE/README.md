# MFGMS AI — Backend (Sprint 1)

FastAPI + SQLAlchemy (async) + PostgreSQL (Neon). Đăng nhập bằng Firebase Authentication; backend đổi Firebase ID token lấy phiên ứng dụng và quản trị người dùng, phân quyền theo dòng họ (clan).

Đã cài: xác thực (`/auth/*`), quản trị người dùng và ủy quyền Family Admin. Chưa cài: đăng ký/duyệt Business, cấp Owner (Mốc E), reset mật khẩu qua BE. Xem [`docs/api_contract.md`](docs/api_contract.md) (bảng "Trạng thái cài đặt").

## Tài liệu

| Tài liệu | Nội dung |
| --- | --- |
| [`docs/handoff_frontend.md`](docs/handoff_frontend.md) | Dành cho Frontend: luồng đăng nhập, phiên hạn chế, mã lỗi, phân trang, ví dụ |
| [`docs/api_contract.md`](docs/api_contract.md) | Hợp đồng API và các quyết định đã chốt |
| [`docs/testing.md`](docs/testing.md) | Cách chạy seed, test thường, test tích hợp; số liệu mới nhất |
| [`docs/security_review.md`](docs/security_review.md) | Kết quả rà soát bảo mật (chỉ ghi điều đã kiểm chứng) |
| [`docs/known_issues.md`](docs/known_issues.md) | Vấn đề đã biết và việc chờ trưởng nhóm quyết định |
| [`docs/BE_Sprint1_Coding_Plan.md`](docs/BE_Sprint1_Coding_Plan.md) | Kế hoạch Sprint 1 |

## Chạy trên máy dev (Windows)

Yêu cầu: Python 3.13, một nhánh PostgreSQL/Neon **cá nhân** (không dùng production).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env          # rồi điền giá trị thật vào .env (không commit)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

Mở `http://localhost:8001/docs` để xem OpenAPI. `GET /api/health` (liveness), `GET /api/health/ready` (readiness: kiểm tra `SELECT 1`; `503` khi database lỗi).

## Biến môi trường

Đọc từ môi trường hoặc `BE/.env`. **Không bao giờ commit `.env` hay file service account.**

| Biến | Bắt buộc | Ý nghĩa |
| --- | --- | --- |
| `DATABASE_URL` | Có | `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require` (`postgresql://` và `postgres://` được chuẩn hóa; SQLite bị từ chối). Thiếu hoặc sai định dạng thì app không import được; thông báo lỗi **không** in chuỗi kết nối |
| `FIREBASE_PROJECT_ID` | Có (khi chạy app) | Project Firebase; là `audience` của ID token. Thiếu thì app **dừng khi khởi động** |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Không | Đường dẫn file service account, chỉ cần cho Admin API (đổi mật khẩu, kiểm tra token bị thu hồi). Nếu khai báo mà file không tồn tại thì app dừng khi khởi động. Code không đọc hay in nội dung/đường dẫn file |
| `FRONTEND_ORIGINS` | Nên có | Các origin được CORS cho phép, phân cách bằng dấu phẩy. Chứa `*` thì app dừng khi khởi động |
| `FRONTEND_URL` | Không | URL của FE |
| `SESSION_TTL_HOURS` | Không | Hạn phiên, mặc định 8 |
| `RECENT_LOGIN_MAX_AGE_SECONDS` | Không | Độ mới của `recent_id_token`, mặc định 300 |
| `DEBUG` | Không | `true` thêm traceback vào log server khi lỗi 500 (không bao giờ vào response). Chỉ dùng khi phát triển |
| `SMTP_*` | Không | Chưa dùng (chờ Mốc E) |

Không đặt `FIREBASE_AUTH_EMULATOR_HOST`: ở chế độ emulator, Admin SDK chấp nhận token không có chữ ký, nên backend từ chối khởi động.

**Máy dev có `.env` cũ:** `FIREBASE_CREDENTIALS_PATH` đã đổi tên thành `FIREBASE_SERVICE_ACCOUNT_PATH` và `FIREBASE_PROJECT_ID` không còn giá trị mặc định (chi tiết ở [`docs/testing.md`](docs/testing.md) mục 0).

Kiểm tra cấu hình Firebase/CORS chạy trong sự kiện khởi động của app, **không** chạy khi import, nên `alembic` và công cụ khác không cần các biến Firebase.

## Test

```powershell
.venv\Scripts\python.exe -m pytest -q                                   # test thường, không cần database
$env:ALLOW_DB_TESTS = "1"; .venv\Scripts\python.exe -m pytest -m integration -q   # trên PostgreSQL thật, mất vài chục phút
```

Test không gọi Firebase thật và không phụ thuộc `.env` cho cấu hình Firebase/CORS. Chi tiết, seed dữ liệu dev và số liệu mới nhất: [`docs/testing.md`](docs/testing.md).

## Docker

```powershell
docker build -t mfgms-be .
docker run --rm -p 8000:8000 `
  -e DATABASE_URL="..." -e FIREBASE_PROJECT_ID="..." -e FRONTEND_ORIGINS="https://app.example" `
  mfgms-be
```

Image chỉ chứa `app/`, `alembic/` và `alembic.ini`: không có `scripts/`, `tests/`, `docs/`, `.env` hay file service account. Chạy bằng user không phải root, có `HEALTHCHECK` trỏ `/api/health`. Muốn dùng Admin API, mount file service account vào container và đặt `FIREBASE_SERVICE_ACCOUNT_PATH` trỏ tới đường dẫn trong container (đừng build file vào image).

Sau reverse proxy: `login_history` ghi IP của proxy trừ khi chạy uvicorn với `--proxy-headers` và danh sách proxy tin cậy (`docs/known_issues.md` KI-11).

## Cấu trúc

```
app/
  main.py                 tạo app, middleware (RequestId > CORS > bắt lỗi chưa xử lý), startup
  core/                   cấu hình, lỗi và envelope, request_id, firebase adapter, kiểm tra khởi động
  db/                     engine, session, kiểm tra kết nối
  dependencies/           xác thực phiên (auth.py), phân quyền (permissions.py)
  controllers/auth_access router + use case: auth, quản trị người dùng, ủy quyền FA
  models/                 ORM (user_access, family), repository, registry cho Alembic
  schemas/                Pydantic request/response, mã lỗi
alembic/                  cấu hình migration (chưa có revision: baseline do trưởng nhóm chốt)
scripts/                  seed dev, đối chiếu ORM với DB (không vào image Docker)
tests/                    test thường; tests/integration chạy trên PostgreSQL thật
docs/                     tài liệu
```

## Migration

Chưa có revision Alembic nào; baseline do trưởng nhóm chốt và duyệt. Không chạy `alembic upgrade`/`stamp` trên database dùng chung khi chưa được duyệt. `scripts/check_orm_vs_db.py` đối chiếu ORM với schema thật (chỉ đọc).
