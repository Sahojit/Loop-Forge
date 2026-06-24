"""
Run this once to apply Loop Studio schema migrations.
Usage: PYTHONPATH=. python db/migrate.py
"""
import asyncio
import os
import logging

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_migrations() -> None:
    from db.postgres import get_pool
    from db.models import CREATE_TABLES_SQL, LOOP_STUDIO_TABLES_SQL

    pool = await get_pool()
    async with pool.acquire() as conn:
        logger.info("Applying base schema...")
        await conn.execute(CREATE_TABLES_SQL)
        logger.info("Applying Loop Studio schema...")
        await conn.execute(LOOP_STUDIO_TABLES_SQL)
        logger.info("Migrations complete.")


if __name__ == "__main__":
    asyncio.run(run_migrations())
