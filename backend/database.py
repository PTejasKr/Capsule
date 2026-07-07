import os
import re
import json
import logging
import sqlite3
import aiosqlite
import asyncpg
from backend.config import settings

logger = logging.getLogger("capsule.database")

# Extract filepath from sqlite+aiosqlite:///./data/capsule.db or similar
def get_db_path() -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite+aiosqlite:///"):
        path = url.replace("sqlite+aiosqlite:///", "")
    elif url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "")
    else:
        # PostgreSQL doesn't need a local DB directory created
        return ""
    
    # Ensure directory exists for SQLite
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        try:
            os.makedirs(dir_name, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create database directory: {e}")
    return path

DB_PATH = get_db_path()

# Global postgres pool
pg_pool = None

def is_pg() -> bool:
    return settings.DATABASE_URL.startswith("postgresql") or settings.DATABASE_URL.startswith("postgres")

async def get_pg_pool():
    global pg_pool
    if pg_pool is None:
        url = settings.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://")
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://")
        logger.info(f"Connecting to PostgreSQL database pool...")
        pg_pool = await asyncpg.create_pool(url)
    return pg_pool

def convert_placeholders(sql: str, is_postgres: bool) -> str:
    if not is_postgres:
        return sql
    # Replace '?' with '$1', '$2', ...
    count = 1
    new_sql = []
    for part in sql.split('?'):
        new_sql.append(part)
        new_sql.append(f"${count}")
        count += 1
    new_sql.pop() # remove last $count
    return "".join(new_sql)

async def init_db():
    if is_pg():
        logger.info("Initializing PostgreSQL database...")
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # Create profiles
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    changelog_repo TEXT NOT NULL,
                    ai_model TEXT NOT NULL,
                    brd_content TEXT,
                    github_token TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create brd_versions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS brd_versions (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    version TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hash TEXT NOT NULL UNIQUE,
                    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE
                )
            """)

            # Create repository_mappings
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS repository_mappings (
                    source_repo TEXT PRIMARY KEY,
                    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create pr_analyses
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pr_analyses (
                    pr_number INTEGER NOT NULL,
                    repo TEXT NOT NULL,
                    title TEXT,
                    summary TEXT,
                    original_summary TEXT,
                    branch TEXT,
                    approved BOOLEAN DEFAULT FALSE,
                    changes_json TEXT,
                    workflow_impact_json TEXT,
                    confidence_score REAL,
                    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (pr_number, repo)
                )
            """)
            
            # Create changelog_entries
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS changelog_entries (
                    id SERIAL PRIMARY KEY,
                    version TEXT NOT NULL,
                    date TEXT NOT NULL,
                    technical_changes_json TEXT,
                    workflow_changes_json TEXT,
                    lines_added INTEGER,
                    lines_deleted INTEGER,
                    pr_number INTEGER,
                    pushed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create audit_log
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    pr_number INTEGER,
                    input_hash TEXT,
                    output_json TEXT,
                    model TEXT,
                    tokens INTEGER,
                    latency_ms REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Seed default profile with ID=1 if not exists
            row = await conn.fetchrow("SELECT id FROM profiles WHERE id = 1")
            if not row:
                await conn.execute("""
                    INSERT INTO profiles (id, name, changelog_repo, ai_model, brd_content)
                    VALUES (1, 'default', '', 'meta/llama-3.3-70b-instruct', 'Default BRD')
                """)
                # Sync serialization sequence
                try:
                    await conn.execute("SELECT setval('profiles_id_seq', 1)")
                except Exception:
                    pass
                logger.info("Seeded default profile with ID 1 in PostgreSQL")
        logger.info("PostgreSQL database tables initialized successfully")
    else:
        logger.info(f"Initializing SQLite database at: {DB_PATH}")
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            # Create profiles
            await db.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    changelog_repo TEXT NOT NULL,
                    ai_model TEXT NOT NULL,
                    brd_content TEXT,
                    github_token TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create brd_versions
            await db.execute("""
                CREATE TABLE IF NOT EXISTS brd_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    version TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hash TEXT NOT NULL UNIQUE,
                    profile_id INTEGER NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
                )
            """)

            # Create repository_mappings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS repository_mappings (
                    source_repo TEXT PRIMARY KEY,
                    profile_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
                )
            """)
            
            # Create pr_analyses
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pr_analyses (
                    pr_number INTEGER NOT NULL,
                    repo TEXT NOT NULL,
                    title TEXT,
                    summary TEXT,
                    original_summary TEXT,
                    branch TEXT,
                    approved BOOLEAN DEFAULT 0,
                    changes_json TEXT,
                    workflow_impact_json TEXT,
                    confidence_score REAL,
                    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (pr_number, repo)
                )
            """)
            
            # Create changelog_entries
            await db.execute("""
                CREATE TABLE IF NOT EXISTS changelog_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL,
                    date TEXT NOT NULL,
                    technical_changes_json TEXT,
                    workflow_changes_json TEXT,
                    lines_added INTEGER,
                    lines_deleted INTEGER,
                    pr_number INTEGER,
                    pushed_at TIMESTAMP
                )
            """)
            
            # Create audit_log
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pr_number INTEGER,
                    input_hash TEXT,
                    output_json TEXT,
                    model TEXT,
                    tokens INTEGER,
                    latency_ms REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Seed default profile with ID=1 if not exists
            async with db.execute("SELECT id FROM profiles WHERE id = 1") as cursor:
                row = await cursor.fetchone()
            if not row:
                await db.execute("""
                    INSERT INTO profiles (id, name, changelog_repo, ai_model, brd_content)
                    VALUES (1, 'default', '', 'meta/llama-3.3-70b-instruct', 'Default BRD')
                """)
                logger.info("Seeded default profile with ID 1 in SQLite")
            
            await db.commit()
        logger.info("SQLite database tables initialized successfully")

async def get_db():
    if is_pg():
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            yield conn
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            yield db

async def execute_query(sql: str, params: tuple = ()) -> int:
    is_postgres = is_pg()
    sql_converted = convert_placeholders(sql, is_postgres)
    
    if is_postgres:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            res = await conn.execute(sql_converted, *params)
            if res:
                parts = res.split(" ")
                if len(parts) > 1 and parts[-1].isdigit():
                    return int(parts[-1])
            return 1
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(sql_converted, params) as cursor:
                await db.commit()
                return cursor.rowcount

async def fetch_one(sql: str, params: tuple = ()) -> dict:
    is_postgres = is_pg()
    sql_converted = convert_placeholders(sql, is_postgres)
    
    if is_postgres:
        pool = await get_pg_pool()
        row = await pool.fetchrow(sql_converted, *params)
        return dict(row) if row else None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql_converted, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

async def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    is_postgres = is_pg()
    sql_converted = convert_placeholders(sql, is_postgres)
    
    if is_postgres:
        pool = await get_pg_pool()
        rows = await pool.fetch(sql_converted, *params)
        return [dict(row) for row in rows]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql_converted, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

async def insert(table: str, data: dict) -> int:
    keys = list(data.keys())
    values = list(data.values())
    
    processed_values = []
    for val in values:
        if isinstance(val, (dict, list)):
            processed_values.append(json.dumps(val))
        elif isinstance(val, bool) and not is_pg():
            processed_values.append(1 if val else 0)
        else:
            processed_values.append(val)
            
    is_postgres = is_pg()
    if is_postgres:
        pool = await get_pg_pool()
        conflict_targets = []
        if table == "pr_analyses":
            conflict_targets = ["pr_number", "repo"]
        elif table == "profiles":
            conflict_targets = ["name"]
        elif table == "repository_mappings":
            conflict_targets = ["source_repo"]
        elif table == "brd_versions":
            conflict_targets = ["hash"]

        # Security: validate table and column names against a strict allowlist
        # to prevent SQL injection through dynamic SQL construction. (Bandit B608)
        _ALLOWED_TABLES = {
            "pr_analyses", "profiles", "repository_mappings",
            "brd_versions", "changelog_entries", "audit_log"
        }
        _ALLOWED_COLUMNS = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

        if table not in _ALLOWED_TABLES:
            raise ValueError(f"INSERT rejected: table '{table}' is not in the allowlist.")
        for col in keys:
            if not _ALLOWED_COLUMNS.match(col):
                raise ValueError(f"INSERT rejected: column name '{col}' contains invalid characters.")

        placeholders = ", ".join([f"${i+1}" for i in range(len(keys))])
        columns = ", ".join(keys)

        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"  # nosec B608 — table/col names are allowlisted above

        if conflict_targets:
            conflict_cols = ", ".join(conflict_targets)
            update_cols = [k for k in keys if k not in conflict_targets]
            if update_cols:
                update_stmt = ", ".join([f"{col} = EXCLUDED.{col}" for col in update_cols])
                sql += f" ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_stmt}"  # nosec B608 — cols from allowlist
            else:
                sql += f" ON CONFLICT ({conflict_cols}) DO NOTHING"
        
        if table in ["brd_versions", "profiles", "changelog_entries", "audit_log"]:
            sql += " RETURNING id"
        
        async with pool.acquire() as conn:
            if "RETURNING id" in sql:
                row_id = await conn.fetchval(sql, *processed_values)
                return row_id
            else:
                await conn.execute(sql, *processed_values)
                return 1
    else:
        placeholders = ", ".join(["?"] * len(keys))
        columns = ", ".join(keys)
        sql = f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})"
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(sql, processed_values) as cursor:
                await db.commit()
                return cursor.lastrowid

async def execute(sql: str, params: tuple = ()) -> None:
    is_postgres = is_pg()
    sql_converted = convert_placeholders(sql, is_postgres)
    if is_postgres:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql_converted, *params)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(sql_converted, params)
            await db.commit()

