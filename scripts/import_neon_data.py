"""Script hỗ trợ chạy nhanh import dữ liệu mẫu vào Neon PostgreSQL từ file seed_neon_real_data.sql."""

import asyncio
import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows console and compatible event loop for psycopg
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Nạp config từ .env
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings

SQL_FILE_PATH = Path(__file__).resolve().parent.parent / "database" / "seed_neon_real_data.sql"


async def main():
    print(f"[*] Đang đọc file SQL: {SQL_FILE_PATH}")
    if not SQL_FILE_PATH.exists():
        print(f"[!] Không tìm thấy file {SQL_FILE_PATH}")
        sys.exit(1)

    with open(SQL_FILE_PATH, "r", encoding="utf-8") as f:
        sql_content = f.read()

    db_url = settings.DATABASE_URL
    # Đảm bảo dùng async driver asyncpg hoặc psycopg async
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    print(f"[*] Đang kết nối tới Neon Database...")
    engine = create_async_engine(db_url, echo=False)

    try:
        # Tách các statement theo dấu chấm phẩy
        statements = []
        current = []
        for line in sql_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or not stripped:
                continue
            if stripped in ("BEGIN;", "COMMIT;"):
                continue
            current.append(line)
            if stripped.endswith(";"):
                stmt = "\n".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []

        print(f"[*] Đang thực thi {len(statements)} khối lệnh SQL...")
        async with engine.begin() as conn:
            for i, stmt in enumerate(statements, 1):
                try:
                    await conn.execute(text(stmt))
                except Exception as stmt_err:
                    print(f"\n[!] Lỗi ở câu lệnh #{i}:\n{stmt}\n=> Lỗi: {stmt_err}\n")
                    raise stmt_err

            print("[✓] THÀNH CÔNG! Toàn bộ câu lệnh SQL đã được nạp trọn vẹn vào Neon DB.")

        # In thông tin thống kê kiểm tra
        async with engine.connect() as conn:
            u_count = (await conn.execute(text("SELECT count(*) FROM users WHERE email IN ('thangvo250904@gmail.com', 'maiphuchau144@gmail.com', 'huy13052005@gmail.com', 'quankophaiwibu@gmail.com', 'vo.danang@giapha.com', 'mai.phongdien@giapha.com');"))).scalar()
            c_count = (await conn.execute(text("SELECT count(*) FROM clans WHERE clan_code IN ('CLAN-VO-01', 'CLAN-MAI-02');"))).scalar()
            p_count = (await conn.execute(text("SELECT count(*) FROM persons;"))).scalar()
            r_count = (await conn.execute(text("SELECT count(*) FROM relationships;"))).scalar()
            print("==================================================")
            print(f"[+] Số tài khoản thật & Trưởng tộc đã nạp/cập nhật: {u_count} / 6")
            print(f"[+] Số dòng họ thực tế: {c_count} (Họ Võ Đại Tộc & Họ Mai Thế Tộc)")
            print(f"[+] Tổng số thành viên gia phả (Persons): {p_count}")
            print(f"[+] Tổng số mối quan hệ gia tộc (Relationships): {r_count}")
            print("==================================================")
    except Exception as e:
        import traceback
        print(f"[!] Lỗi khi import dữ liệu vào Neon: {e}")
        traceback.print_exc()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
