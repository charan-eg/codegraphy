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

    def get_file_hash(self, file_path: str) -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("SELECT git_hash FROM cg_files WHERE file_path = %s", (file_path,))
            else:
                cursor.execute("SELECT git_hash FROM cg_files WHERE file_path = ?", (file_path,))
            row = cursor.fetchone()
            return row[0] if row else None

    def upsert_file(self, file_path: str, git_hash: str, symbols: list, edges: list):
        """
        Replace symbols and edges for a file.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Param style
            p = "%s" if self.is_postgres else "?"
            
            # Upsert file
            if self.is_postgres:
                cursor.execute(f"""
                    INSERT INTO cg_files (file_path, git_hash, symbol_count, last_indexed)
                    VALUES ({p}, {p}, {p}, NOW())
                    ON CONFLICT (file_path) DO UPDATE 
                    SET git_hash = EXCLUDED.git_hash, symbol_count = EXCLUDED.symbol_count, last_indexed = NOW()
                """, (file_path, git_hash, len(symbols)))
            else:
                cursor.execute(f"""
                    INSERT INTO cg_files (file_path, git_hash, symbol_count, last_indexed)
                    VALUES ({p}, {p}, {p}, CURRENT_TIMESTAMP)
                    ON CONFLICT(file_path) DO UPDATE 
                    SET git_hash=excluded.git_hash, symbol_count=excluded.symbol_count, last_indexed=CURRENT_TIMESTAMP
                """, (file_path, git_hash, len(symbols)))

            # Delete old symbols (cascade deletes edges)
            cursor.execute(f"DELETE FROM cg_symbols WHERE file_path = {p}", (file_path,))

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
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                """, symbol_records)

            # To insert edges, we need their IDs. The simplest way is to map qualified_name -> id
            # Note: For edges where the target doesn't exist yet, we might have missing IDs.
            # To handle this robustly without failing, we only insert edges where both from and to exist.
            # However, the spec says from_id, to_id.
            # We must get IDs for all symbols first.
            
            # For simplicity in this step, we will bulk insert edges later or inside a second pass?
            # Actually we can just look up ids.
            # If to_qualified doesn't exist in DB, the edge is dropped.
            if edges:
                quals = set()
                for e in edges:
                    quals.add(e.from_qualified)
                    quals.add(e.to_qualified)
                
                if quals:
                    # SQLite limit for variables is 999, but a single file rarely exceeds that.
                    # For safety, we can query in batches, or use placeholders.
                    quals_list = list(quals)
                    qual_to_id = {}
                    
                    # Batch fetch to avoid hitting sqlite limits
                    batch_size = 500
                    for i in range(0, len(quals_list), batch_size):
                        batch = quals_list[i:i+batch_size]
                        placeholders = ",".join([p] * len(batch))
                        cursor.execute(f"SELECT id, qualified_name FROM cg_symbols WHERE qualified_name IN ({placeholders})", tuple(batch))
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
                            VALUES ({p}, {p}, {p})
                            ON CONFLICT DO NOTHING
                        """, edge_records)
