PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS cg_files (
    id          SERIAL PRIMARY KEY,
    file_path   TEXT UNIQUE NOT NULL,
    module_path TEXT,
    summary     TEXT,
    symbol_count INTEGER DEFAULT 0,
    git_hash    TEXT,
    last_indexed TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cg_symbols (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    qualified_name  TEXT UNIQUE NOT NULL,
    kind            TEXT NOT NULL,
    file_path       TEXT NOT NULL REFERENCES cg_files(file_path) ON DELETE CASCADE,
    line_start      INTEGER,
    line_end        INTEGER,
    summary         TEXT,
    raw_signature   TEXT,
    extra           JSONB,
    last_indexed    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cg_edges (
    from_id  INTEGER NOT NULL REFERENCES cg_symbols(id) ON DELETE CASCADE,
    to_id    INTEGER NOT NULL REFERENCES cg_symbols(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_symbols_name       ON cg_symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file       ON cg_symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_kind       ON cg_symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_qualname   ON cg_symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_edges_from         ON cg_edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to           ON cg_edges(to_id);
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cg_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT UNIQUE NOT NULL,
    module_path TEXT,
    summary     TEXT,
    symbol_count INTEGER DEFAULT 0,
    git_hash    TEXT,
    last_indexed DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cg_symbols (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    qualified_name  TEXT UNIQUE NOT NULL,
    kind            TEXT NOT NULL,
    file_path       TEXT NOT NULL REFERENCES cg_files(file_path) ON DELETE CASCADE,
    line_start      INTEGER,
    line_end        INTEGER,
    summary         TEXT,
    raw_signature   TEXT,
    extra           TEXT,
    last_indexed    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cg_edges (
    from_id  INTEGER NOT NULL REFERENCES cg_symbols(id) ON DELETE CASCADE,
    to_id    INTEGER NOT NULL REFERENCES cg_symbols(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_symbols_name       ON cg_symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file       ON cg_symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_kind       ON cg_symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_qualname   ON cg_symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_edges_from         ON cg_edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to           ON cg_edges(to_id);
"""

def get_schema(db_url: str) -> str:
    if db_url.startswith("postgres"):
        return PG_SCHEMA
    return SQLITE_SCHEMA
