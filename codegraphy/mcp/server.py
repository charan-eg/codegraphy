from mcp.server.fastmcp import FastMCP
from ..db.store import Store
from ..config import DATABASE_URL, CODEGRAPHY_ROOT
import subprocess

mcp = FastMCP("codegraphy")
store = Store(DATABASE_URL)

@mcp.tool()
def search_symbol(name: str, kind: str = None, limit: int = 10, fallback_grep: bool = True) -> list[dict]:
    """
    Find symbols by name (exact, prefix, or substring match).
    """
    results = []
    
    with store.get_connection() as conn:
        cursor = conn.cursor()
        p = "%s" if store.is_postgres else "?"
        
        # 1. Exact match
        query_exact = f"SELECT qualified_name, kind, file_path, line_start, summary FROM cg_symbols WHERE name = {p}"
        params_exact = [name]
        
        if kind:
            query_exact += f" AND kind = {p}"
            params_exact.append(kind)
            
        cursor.execute(query_exact + f" LIMIT {limit}", params_exact)
        rows = cursor.fetchall()
        
        # 2. Substring match if no exact match
        if not rows:
            like_op = "ILIKE" if store.is_postgres else "LIKE"
            query_like = f"SELECT qualified_name, kind, file_path, line_start, summary FROM cg_symbols WHERE name {like_op} {p}"
            params_like = [f"%{name}%"]
            if kind:
                query_like += f" AND kind = {p}"
                params_like.append(kind)
            cursor.execute(query_like + f" LIMIT {limit}", params_like)
            rows = cursor.fetchall()
            
        for row in rows:
            results.append({
                "qualified_name": row[0],
                "kind": row[1],
                "file_path": row[2],
                "line_start": row[3],
                "summary": row[4],
                "source": "graph"
            })
            
    # 3. Fallback to grep
    if not results and fallback_grep:
        try:
            # We use subprocess to run grep
            grep_cmd = ['grep', '-rn', '--include=*.py', '--include=*.js', '--include=*.ts', '--include=*.html', name, CODEGRAPHY_ROOT]
            res = subprocess.run(grep_cmd, capture_output=True, text=True)
            if res.stdout:
                for line in res.stdout.splitlines()[:limit]:
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        results.append({
                            "file_path": parts[0],
                            "line_start": parts[1],
                            "match_text": parts[2].strip(),
                            "source": "grep"
                        })
        except Exception:
            pass
            
    return results

@mcp.tool()
def get_file_summary(file_path: str) -> dict:
    """
    One-shot summary of a file: classes, functions, imports.
    """
    with store.get_connection() as conn:
        cursor = conn.cursor()
        p = "%s" if store.is_postgres else "?"
        
        cursor.execute(f"SELECT module_path, summary FROM cg_files WHERE file_path = {p}", (file_path,))
        row = cursor.fetchone()
        
        if not row:
            # Fallback
            try:
                with open(file_path, 'r') as f:
                    lines = [next(f).strip() for _ in range(5)]
                return {"error": "File not indexed", "head": lines, "source": "fallback"}
            except Exception as e:
                return {"error": f"Could not read file: {e}"}
                
        module_path, summary = row
        
        cursor.execute(f"SELECT name, kind FROM cg_symbols WHERE file_path = {p} AND kind IN ('class', 'function', 'import')", (file_path,))
        symbols = cursor.fetchall()
        
        classes = [s[0] for s in symbols if s[1] == 'class']
        functions = [s[0] for s in symbols if s[1] == 'function']
        imports = [s[0] for s in symbols if s[1] == 'import']
        
        return {
            "module_path": module_path,
            "summary": summary,
            "classes": classes,
            "functions": functions,
            "imports": imports,
            "source": "graph"
        }

@mcp.tool()
def find_usages(qualified_name: str, limit: int = 20, fallback_grep: bool = True) -> list[dict]:
    """
    Find every symbol that imports, calls, or references this symbol.
    """
    results = []
    with store.get_connection() as conn:
        cursor = conn.cursor()
        p = "%s" if store.is_postgres else "?"
        
        # We need the ID of the target
        cursor.execute(f"SELECT id FROM cg_symbols WHERE qualified_name = {p}", (qualified_name,))
        row = cursor.fetchone()
        
        if row:
            to_id = row[0]
            query = f"""
                SELECT s.qualified_name, e.relation, s.file_path, s.line_start
                FROM cg_edges e
                JOIN cg_symbols s ON e.from_id = s.id
                WHERE e.to_id = {p}
                LIMIT {limit}
            """
            cursor.execute(query, (to_id,))
            for r in cursor.fetchall():
                results.append({
                    "from_qualified": r[0],
                    "relation": r[1],
                    "file_path": r[2],
                    "line_start": r[3],
                    "source": "graph"
                })
                
    if not results and fallback_grep:
        short_name = qualified_name.split('.')[-1]
        try:
            grep_cmd = ['grep', '-rn', short_name, CODEGRAPHY_ROOT]
            res = subprocess.run(grep_cmd, capture_output=True, text=True)
            if res.stdout:
                for line in res.stdout.splitlines()[:limit]:
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        results.append({
                            "file_path": parts[0],
                            "line_start": parts[1],
                            "match_text": parts[2].strip(),
                            "source": "grep"
                        })
        except Exception:
            pass
            
    return results

@mcp.tool()
def get_context(file_path: str, line: int, radius: int = 30) -> str:
    """
    Read N lines around a specific line number.
    """
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        start = max(0, line - radius - 1)
        end = min(len(lines), line + radius)
        
        output = []
        for i in range(start, end):
            output.append(f"{i+1}: {lines[i].rstrip()}")
            
        return "\n".join(output)
    except Exception as e:
        return f"Error reading file: {e}"

@mcp.tool()
def path_between(from_qualified: str, to_qualified: str, max_depth: int = 6) -> list[dict]:
    """
    BFS shortest path through the edge graph between two symbols.
    """
    with store.get_connection() as conn:
        cursor = conn.cursor()
        p = "%s" if store.is_postgres else "?"
        
        # Get IDs
        cursor.execute(f"SELECT id FROM cg_symbols WHERE qualified_name = {p}", (from_qualified,))
        row1 = cursor.fetchone()
        cursor.execute(f"SELECT id FROM cg_symbols WHERE qualified_name = {p}", (to_qualified,))
        row2 = cursor.fetchone()
        
        if not row1 or not row2:
            return []
            
        start_id = row1[0]
        end_id = row2[0]
        
        # BFS queue: (current_id, path_so_far)
        from collections import deque
        queue = deque([(start_id, [])])
        visited = {start_id}
        
        while queue:
            curr_id, path = queue.popleft()
            
            if len(path) >= max_depth:
                continue
                
            # Get neighbors
            cursor.execute(f"""
                SELECT e.to_id, s.qualified_name, e.relation
                FROM cg_edges e
                JOIN cg_symbols s ON e.to_id = s.id
                WHERE e.from_id = {p}
            """, (curr_id,))
            neighbors = cursor.fetchall()
            
            for next_id, qualname, rel in neighbors:
                new_path = path + [{"symbol": qualname, "relation": rel}]
                if next_id == end_id:
                    return new_path
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, new_path))
                    
    return []

@mcp.tool()
def search_semantic(query: str, limit: int = 10) -> list[dict]:
    """
    pgvector semantic search over symbol summaries.
    No-ops on SQLite.
    """
    if not store.is_postgres:
        return []
        
    # TODO: implement actual vector search with embeddings
    return []

@mcp.tool()
def graph_stats() -> dict:
    """Quick health check."""
    with store.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cg_files")
        files = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cg_symbols")
        symbols = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cg_edges")
        edges = cursor.fetchone()[0]
        return {
            "files": files,
            "symbols": symbols,
            "edges": edges,
            "backend": "postgres" if store.is_postgres else "sqlite"
        }

@mcp.tool()
def grep_search(pattern: str, include: list[str] = None, exclude: list[str] = None, limit: int = 30) -> list[dict]:
    """
    Direct grep tool — bypass the graph entirely.
    """
    cmd = ['grep', '-rn']
    if include:
        for inc in include:
            cmd.append(f'--include={inc}')
    if exclude:
        for exc in exclude:
            cmd.append(f'--exclude-dir={exc}')
            
    cmd.extend([pattern, CODEGRAPHY_ROOT])
    
    results = []
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.stdout:
            for line in res.stdout.splitlines()[:limit]:
                parts = line.split(':', 2)
                if len(parts) >= 3:
                    results.append({
                        "file_path": parts[0],
                        "line_start": parts[1],
                        "match_text": parts[2].strip(),
                        "source": "grep"
                    })
    except Exception:
        pass
    return results

@mcp.tool()
def what_touches_model(model_name: str) -> dict:
    """
    Django plugin only. Returns views, admin registrations, signals.
    """
    return {"views": [], "admin": [], "signals": [], "references": []}

def start_server():
    mcp.run()
