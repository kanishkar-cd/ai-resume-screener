import asyncio

from sqlalchemy import text

from app.db.session import engine


async def main() -> None:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'parsed_documents' "
                "ORDER BY ordinal_position"
            )
        )
        for row in rows:
            print(row)
        ver = await conn.execute(text("SELECT version_num FROM alembic_version"))
        print("alembic:", list(ver))


asyncio.run(main())
