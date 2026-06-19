# Contributing to codegraphy

Thanks for your interest in contributing! This document covers how to set up a development environment, the project conventions, and how to submit changes.

---

## Getting Started

### Prerequisites

- Python 3.10+
- Git
- (Optional) PostgreSQL for testing Postgres backend
- (Optional) `tree-sitter` for JS/TS/HTML indexer work

### Setup

```bash
git clone <repo-url>
cd codegraphy

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e ".[all]"
```

### Verify Installation

```bash
codegraphy init
codegraphy index .
codegraphy stats
```

---

## Project Structure

```
codegraphy/
├── cli.py              # Click CLI — add new commands here
├── config.py           # Configuration loading (env vars, TOML)
├── db/
│   ├── schema.py       # DDL for PG and SQLite
│   └── store.py        # Database abstraction layer
├── indexer/
│   ├── base.py         # BaseIndexer ABC, Symbol/Edge dataclasses
│   ├── python.py       # Python AST indexer
│   └── walker.py       # File discovery + incremental indexing
├── mcp/
│   └── server.py       # MCP tool definitions (FastMCP)
├── plugins/
│   ├── base.py         # BasePlugin ABC
│   └── django.py       # Django framework plugin
└── session/            # Session hooks (planned)
```

---

## How to Contribute

### Adding a New Indexer (e.g., JS/TS, HTML)

1. Create `codegraphy/indexer/<language>.py`
2. Subclass `BaseIndexer` from `codegraphy/indexer/base.py`:
   ```python
   class JavaScriptIndexer(BaseIndexer):
       def can_handle(self, file_path: str) -> bool:
           return file_path.endswith(('.js', '.ts', '.jsx', '.tsx'))

       def index_file(self, file_path: str, source: str) -> tuple[list[Symbol], list[Edge]]:
           # Parse and return symbols + edges
           ...
   ```
3. Register in `codegraphy/indexer/walker.py`:
   ```python
   INDEXERS = [PythonIndexer(), JavaScriptIndexer()]
   ```
4. Add tests in `tests/test_indexer.py`

### Adding a New Plugin

1. Create `codegraphy/plugins/<name>.py`
2. Subclass `BasePlugin`:
   ```python
   class MyPlugin(BasePlugin):
       def on_symbol(self, symbol: Symbol) -> Symbol:
           # Re-tag or enrich symbols
           return symbol

       def extra_edges(self, symbols: list[Symbol]) -> list[Edge]:
           # Derive additional relationships
           return []
   ```
3. Users enable via `CODEGRAPHY_PLUGINS=codegraphy.plugins.<name>`

### Adding a New MCP Tool

1. Add the function in `codegraphy/mcp/server.py` with the `@mcp.tool()` decorator
2. Follow existing patterns:
   - Accept simple typed parameters
   - Return `list[dict]` or `dict`
   - Include `"source": "graph"` or `"source": "grep"` in responses
   - Support `fallback_grep` parameter where applicable
3. Add a corresponding CLI debug command in `codegraphy/cli.py` if useful

---

## Code Conventions

### Style

- No linter is configured yet — follow existing code style
- Use type hints for function signatures
- Prefer raw SQL over ORM abstractions
- Keep imports at the top of the file; use lazy imports inside functions only for heavy/optional deps

### Database

- All table names prefixed with `cg_` (code graph)
- Support both PostgreSQL and SQLite — use `%s` vs `?` parameterization via `store.is_postgres`
- Never use string interpolation for SQL values; always use parameterized queries

### Naming

- Symbol `qualified_name` follows dotted path: `module.path.ClassName.method_name`
- Edge `relation` values: `imports`, `calls`, `inherits`, `defines`, `references`, `registers`, `handles_signal`
- Symbol `kind` values: `file`, `class`, `function`, `method`, `model`, `view`, `signal`, `import`, `block`

---

## Testing

Tests live in `tests/`. The test suite is not yet built out — this is a high-priority contribution area.

### Running Tests

```bash
# When tests are added:
pip install pytest
pytest tests/
```

### What Needs Tests

- `tests/test_indexer.py` — Python indexer against fixture files
- `tests/test_store.py` — Store CRUD operations (SQLite)
- `tests/test_mcp_tools.py` — MCP tool responses with a seeded database
- `tests/fixtures/` — Small `.py` files for deterministic indexer output

### Writing a Test

```python
# tests/test_indexer.py
from codegraphy.indexer.python import PythonIndexer

def test_extracts_class():
    source = '''
class Foo:
    """A foo class."""
    def bar(self):
        pass
'''
    indexer = PythonIndexer()
    symbols, edges = indexer.index_file("test.py", source)
    classes = [s for s in symbols if s.kind == "class"]
    assert len(classes) == 1
    assert classes[0].name == "Foo"
    assert classes[0].summary == "A foo class."
```

---

## Open Work

These are high-impact areas where contributions are welcome:

| Area | Description | Milestone |
|------|-------------|-----------|
| **Tests** | Add pytest suite for indexer, store, and MCP tools | — |
| **Config loading** | Implement `codegraphy.toml` parsing in `config.load_config()` | — |
| **Plugin wiring** | Instantiate plugins from `CODEGRAPHY_PLUGINS` in CLI commands | M5 |
| **Django plugin** | Admin registration and signal detection via AST decorators | M5 |
| **JS/TS indexer** | tree-sitter-based extraction of functions, classes, imports, calls | M7 |
| **HTML indexer** | Template inheritance, blocks, `{% url %}` references | M8 |
| **Semantic search** | pgvector embeddings for symbol summaries | M6 |
| **Session hook** | `session/hook.py` — auto-update on git changes | M4 |
| **`graph_stats` breakdown** | Per-language symbol/file counts | M2 |

---

## Submitting Changes

1. Fork the repo and create a feature branch
2. Make your changes — keep commits focused and atomic
3. Ensure `codegraphy index .` still works on a sample project
4. Run tests (when available): `pytest tests/`
5. Open a pull request with a clear description of what and why

---

## Publishing a Release

PyPI packaging is driven by `pyproject.toml`.

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

Publish the base package for SQLite users, and keep PostgreSQL support behind the `postgres` extra.

---

## Design Principles

1. **Zero-config works** — SQLite by default, no server required
2. **Incremental by default** — SHA-256 dedup means re-indexing is fast
3. **Grep is the safety net** — when the graph doesn't have it, grep fills in
4. **Plugins enrich, not replace** — base indexers handle syntax; plugins add domain knowledge
5. **Token-efficient responses** — every tool is designed to return minimal, structured data
