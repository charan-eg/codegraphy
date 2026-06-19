import json
import sqlite3
from urllib.parse import urlparse
from contextlib import contextmanager

from .schema import get_schema

try:
    import psycopg2
    from psycopg2.extras import Json
except ImportError:
    psycopg2 = None

class Store:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.is_postgres = db_url.startswith("postgres")
        
        if self.is_postgres and psycopg2 is None:
            raise ImportError("psycopg2-binary is required for postgres support")
            
        if self.is_postgres:
            parsed = urlparse(db_url)
            self.conn_kwargs = {
                'dbname': parsed.path[1:],
                'user': parsed.username,
                'password': parsed.password,
                'host': parsed.hostname,
                'port': parsed.port,
            }
            # Remove None values
            self.conn_kwargs = {k: v for k, v in self.conn_kwargs.items() if v is not None}
        else:
            # Handle sqlite:///path
            self.db_path = db_url.replace("sqlite:///", "")
            if not self.db_path:
                self.db_path = "codegraphy.db"

    @contextmanager
    def get_connection(self):
        if self.is_postgres:
            conn = psycopg2.connect(**self.conn_kwargs)
        else:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self):
        schema_sql = get_schema(self.db_url)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute(schema_sql)
            else:
                # sqlite3 executescript for multiple statements
                cursor.executescript(schema_sql)

    def _placeholder(self) -> str:
        return "%s" if self.is_postgres else "?"

    def _cursor(self, conn):
        return conn.cursor()

    def get_file_hash(self, file_path: str, conn=None) -> str:
        if conn is None:
            with self.get_connection() as managed_conn:
                return self.get_file_hash(file_path, managed_conn)

        cursor = self._cursor(conn)
        cursor.execute(
            f"SELECT git_hash FROM cg_files WHERE file_path = {self._placeholder()}",
            (file_path,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_file_hashes(self, file_paths: list[str], conn=None) -> dict[str, str]:
        if not file_paths:
            return {}

        if conn is None:
            with self.get_connection() as managed_conn:
                return self.get_file_hashes(file_paths, managed_conn)

        cursor = self._cursor(conn)
        placeholder = self._placeholder()
        file_hashes = {}

        batch_size = 500
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i:i + batch_size]
            placeholders = ",".join([placeholder] * len(batch))
            cursor.execute(
                f"SELECT file_path, git_hash FROM cg_files WHERE file_path IN ({placeholders})",
                tuple(batch),
            )
            for file_path, git_hash in cursor.fetchall():
                file_hashes[file_path] = git_hash

        return file_hashes

    def _dedupe_symbols(self, symbols: list) -> list:
        deduped = []
        seen = set()
        for symbol in symbols:
            if symbol.qualified_name in seen:
                continue
            seen.add(symbol.qualified_name)
            deduped.append(symbol)
        return deduped

    def _upsert_file_with_cursor(self, cursor, file_path: str, git_hash: str, symbols: list, edges: list):
        placeholder = self._placeholder()

        # Upsert file
        if self.is_postgres:
            cursor.execute(f"""
                INSERT INTO cg_files (file_path, git_hash, symbol_count, last_indexed)
                VALUES ({placeholder}, {placeholder}, {placeholder}, NOW())
                ON CONFLICT (file_path) DO UPDATE
                SET git_hash = EXCLUDED.git_hash, symbol_count = EXCLUDED.symbol_count, last_indexed = NOW()
            """, (file_path, git_hash, len(symbols)))
        else:
            cursor.execute(f"""
                INSERT INTO cg_files (file_path, git_hash, symbol_count, last_indexed)
                VALUES ({placeholder}, {placeholder}, {placeholder}, CURRENT_TIMESTAMP)
                ON CONFLICT(file_path) DO UPDATE
                SET git_hash=excluded.git_hash, symbol_count=excluded.symbol_count, last_indexed=CURRENT_TIMESTAMP
            """, (file_path, git_hash, len(symbols)))

        # Delete old symbols (cascade deletes edges)
        cursor.execute(f"DELETE FROM cg_symbols WHERE file_path = {placeholder}", (file_path,))

        # Insert new symbols
        if symbols:
            symbol_records = []
            for s in symbols:
                extra_val = Json(s.extra) if self.is_postgres else json.dumps(s.extra)
                symbol_records.append((
                    s.name, s.qualified_name, s.kind, s.file_path,
                    s.line_start, s.line_end, s.summary, s.raw_signature, extra_val
                ))

            cursor.executemany(f"""
                INSERT INTO cg_symbols (name, qualified_name, kind, file_path, line_start, line_end, summary, raw_signature, extra)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
            """, symbol_records)

        if edges:
            quals = set()
            for e in edges:
                quals.add(e.from_qualified)
                quals.add(e.to_qualified)

            if quals:
                quals_list = list(quals)
                qual_to_id = {}

                batch_size = 500
                for i in range(0, len(quals_list), batch_size):
                    batch = quals_list[i:i + batch_size]
                    placeholders = ",".join([placeholder] * len(batch))
                    cursor.execute(
                        f"SELECT id, qualified_name FROM cg_symbols WHERE qualified_name IN ({placeholders})",
                        tuple(batch),
                    )
                    for row in cursor.fetchall():
                        qual_to_id[row[1]] = row[0]

                edge_records = []
                for e in edges:
                    from_id = qual_to_id.get(e.from_qualified)
                    to_id = qual_to_id.get(e.to_qualified)
                    if from_id and to_id:
                        edge_records.append((from_id, to_id, e.relation))

                if edge_records:
                    cursor.executemany(f"""
                        INSERT INTO cg_edges (from_id, to_id, relation)
                        VALUES ({placeholder}, {placeholder}, {placeholder})
                        ON CONFLICT DO NOTHING
                    """, edge_records)

    def upsert_file(self, file_path: str, git_hash: str, symbols: list, edges: list, conn=None):
        """
        Replace symbols and edges for a file.
        """
        symbols = self._dedupe_symbols(symbols)
        if conn is None:
            with self.get_connection() as managed_conn:
                cursor = self._cursor(managed_conn)
                self._upsert_file_with_cursor(cursor, file_path, git_hash, symbols, edges)
            return

        cursor = self._cursor(conn)
        self._upsert_file_with_cursor(cursor, file_path, git_hash, symbols, edges)
