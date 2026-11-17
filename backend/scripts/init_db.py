"""建表脚本：初始化查询日志表（幂等，可重复执行）

用法：
    python backend/scripts/init_db.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.db import repository  # noqa: E402


def main() -> None:
    try:
        count = repository.init_schema()
        print(f"[OK] 已执行 {count} 条建表语句")
        with repository.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [r["table_name"] for r in cur.fetchall()]
        print("[OK] 当前表:", tables or "（空）")
    except Exception as exc:
        print(f"[ERROR] 建表失败: {exc}")
        print("        请确认 .env 的 DATABASE_URL 可用，且 Docker 中的 PostgreSQL 已启动")
        sys.exit(1)


if __name__ == "__main__":
    main()
