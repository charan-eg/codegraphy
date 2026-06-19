# codegraphy

Standalone Python package that parses a codebase into a knowledge graph (PostgreSQL or SQLite) and exposes it as an [MCP](https://modelcontextprotocol.io/) server for Claude Code. Claude calls graph tools instead of `Read` + `Bash(grep)` — cuts exploration token cost by 5–10×.

**PyPI:** https://pypi.org/project/codegraphy/

**Python:** 3.10+  
**License:** MIT

---

## Why

Claude exploring an unfamiliar codebase today:

| Task | Without codegraphy | With codegraphy |
|------|-------------------|----------------|
| Find where `Something` is defined | Read 10 files (~15k tokens) | `search_symbol("Something")` (~200 tokens) |
| Understand a file's structure | Read full file (~3k tokens) | `get_file_summary("views.py")` (~300 tokens) |

---

## Installation

```bash
# SQLite-only install (default, zero config):
pip install codegraphy

# For PostgreSQL support:
pip install codegraphy[postgres]

# For JS/TS parsing (planned):
pip install codegraphy[js]

# Everything:
pip install codegraphy[all]
```

The base PyPI package keeps SQLite support in the standard library path, so PostgreSQL stays opt-in.

---

## PostgreSQL

Install PostgreSQL support:

```bash
pip install 'codegraphy[postgres]'
```

Initialize with a PostgreSQL URL:

```bash
codegraphy init --db postgresql://USER:PASSWORD@HOST:PORT/DBNAME
```

Example:

```bash
codegraphy init --db postgresql://postgres:postgres@localhost:5432/codegraphy
```

Or set `DATABASE_URL` once and reuse it:

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/codegraphy
codegraphy init
codegraphy index .
codegraphy serve
```

---

## Quickstart

```bash
# 1. Initialize the database (SQLite by default)
codegraphy init

# 2. Index your project
codegraphy index .

# 3. Start the MCP server (stdio, for Claude Code)
codegraphy serve
```

That's it. Claude can now query your codebase graph instead of reading files.

---

## CLI Reference

```bash
codegraphy init [--db URL]         # Create tables (SQLite default, or pass Postgres URL)
codegraphy index PATH [--exclude]  # Full index of a directory
codegraphy update                  # Incremental re-index via git diff
codegraphy serve                   # Start MCP server over stdio
codegraphy search NAME             # Search symbols (debug, not MCP)
codegraphy usages QUALIFIED_NAME   # Find usages (debug, not MCP)
codegraphy stats                   # Show graph statistics
```

---

## MCP Tools

When running as an MCP server, codegraphy exposes these tools to Claude:

| Tool | Description |
|------|-------------|
| `search_symbol(name, kind?, limit?, fallback_grep?)` | Find symbols by name — exact, then substring, then grep fallback |
| `get_file_summary(file_path)` | Classes, functions, imports in a file without reading it |
| `find_usages(qualified_name, limit?, fallback_grep?)` | Who imports/calls/references this symbol |
| `get_context(file_path, line, radius?)` | Read N lines around a line number |
| `path_between(from_qualified, to_qualified, max_depth?)` | BFS shortest path between two symbols |
| `grep_search(pattern, include?, exclude?, limit?)` | Direct grep — bypass the graph |
| `graph_stats()` | File/symbol/edge counts, backend type |
| `what_touches_model(model_name)` | Django: views, admin, signals referencing a model |
| `search_semantic(query, limit?)` | pgvector semantic search (Postgres only, planned) |

All tools return a `source` field (`"graph"` or `"grep"`) so Claude can gauge confidence.

---

## Configuration

Priority: CLI flag → environment variable → `codegraphy.toml` → defaults.

### Environment Variables

```bash
DATABASE_URL=sqlite:///codegraphy.db      # or postgresql://localhost/codegraphy
CODEGRAPHY_ROOT=.                         # project root for grep fallback
CODEGRAPHY_PLUGINS=codegraphy.plugins.django
```

### Config File (optional)

```toml
# codegraphy.toml (place at project root)
database_url = "postgresql://localhost/codegraphy"
root = "."
exclude = ["migrations", "node_modules", ".venv", "__pycache__"]
plugins = ["codegraphy.plugins.django"]
```

---

## Claude Code Integration

### Register the MCP server

```json
// .claude/settings.json
{
  "mcpServers": {
    "codegraphy": {
      "command": "codegraphy",
      "args": ["serve"],
      "env": {
        "DATABASE_URL": "sqlite:///codegraphy.db"
      }
    }
  }
}
```

### Auto-update on session end (optional)

```json
// .claude/settings.json
{
  "hooks": {
    "Stop": [{
      "type": "command",
      "command": "codegraphy update"
    }]
  }
}
```

---

## Architecture

```
codegraphy/
├── cli.py              # Click CLI entry points
├── config.py           # DATABASE_URL, CODEGRAPHY_ROOT, plugin list
├── db/
│   ├── schema.py       # CREATE TABLE statements (PG + SQLite)
│   └── store.py        # upsert_symbol, upsert_edge, query helpers
├── indexer/
│   ├── base.py         # BaseIndexer ABC, Symbol/Edge dataclasses
│   ├── python.py       # ast-based Python indexer
│   └── walker.py       # Filesystem walk + git-diff incremental
├── mcp/
│   └── server.py       # FastMCP server + all tool definitions
├── plugins/
│   ├── base.py         # BasePlugin ABC
│   └── django.py       # Django-aware: models, views, signals
└── session/            # (planned) git-diff hook + memory write
```

### Database Schema

Three tables power the graph:

- **`cg_files`** — indexed files with git hash for deduplication
- **`cg_symbols`** — every class, function, method, import with location + summary
- **`cg_edges`** — relationships: `imports`, `calls`, `inherits`, `references`, `registers`, `handles_signal`

### Indexing Strategy

1. Walk files via `git ls-files` (falls back to `os.walk`)
2. SHA-256 content hash skips unchanged files
3. AST parsing extracts symbols and edges
4. Plugins post-process symbols (e.g., Django re-tags `class` → `model`)
5. Upsert into database with cascade delete for clean re-indexing

---

## Plugin System

Plugins implement two hooks:

```python
class BasePlugin:
    def on_symbol(self, symbol: Symbol) -> Symbol:
        """Mutate or re-tag a symbol after parsing."""
        return symbol

    def extra_edges(self, symbols: list[Symbol]) -> list[Edge]:
        """Derive additional edges from the symbol list."""
        return []
```

### Built-in: Django Plugin

Detects Django patterns by file naming convention:
- Classes in `models.py` → `kind = "model"`
- Classes/functions in `views.py` → `kind = "view"`

Enable via environment variable:
```bash
CODEGRAPHY_PLUGINS=codegraphy.plugins.django
```

---

## Current Status

| Milestone | Status |
|-----------|--------|
| M1 — Schema + Python indexer + `codegraphy index` | ✅ Complete |
| M2 — `search_symbol` + `get_file_summary` + MCP serve | ✅ Complete |
| M3 — `find_usages` + `path_between` + `get_context` + grep fallback | ✅ Complete |
| M4 — `codegraphy update` (incremental) | ✅ Complete |
| M5 — Django plugin | 🔶 Partial (symbol re-tagging, no admin/signal edges) |
| M6 — Semantic search (pgvector) | ⬜ Stub only |
| M7 — JS/TS indexer (tree-sitter) | ⬜ Planned |
| M8 — HTML/Template indexer | ⬜ Planned |
| M9 — `grep_search` tool + cross-language edges | 🔶 grep_search done, cross-lang edges planned |

---

## Development

```bash
# Clone and install in editable mode
git clone <repo-url> && cd codegraphy
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Initialize local DB and index this project
codegraphy init
codegraphy index .

# Check stats
codegraphy stats
```

## Publishing

`codegraphy` is configured to build as a standard PyPI distribution from `pyproject.toml`.

For PyPI trusted publishing, use **`publish.yml`** as the workflow name. The workflow file lives at `.github/workflows/publish.yml`.

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

---

## What It Is NOT

- Not a code execution sandbox
- Not a test runner or linter
- Not a replacement for LSP/IDE features
- Not AI-generated summaries by default (uses docstrings; AI summaries are opt-in future)
