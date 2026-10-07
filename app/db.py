from contextlib import asynccontextmanager
from typing import AsyncIterator

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


async def open_pool(dsn: str) -> None:
    global _pool
    _pool = AsyncConnectionPool(
        dsn,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"row_factory": dict_row, "options": "-c search_path=aqap,public"},
    )
    await _pool.open(wait=True)


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


@asynccontextmanager
async def transaction(user_id: int | None = None) -> AsyncIterator[AsyncConnection]:
    """معاملة واحدة لكل طلب؛ تمرير هوية المستخدم لسجل التدقيق في قاعدة البيانات."""
    assert _pool is not None, "connection pool is not open"
    async with _pool.connection() as conn:
        async with conn.transaction():
            if user_id is not None:
                await conn.execute("SELECT set_config('aqap.user_id', %s, true)", (str(user_id),))
            yield conn
