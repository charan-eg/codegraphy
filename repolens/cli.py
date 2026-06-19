import click
from .config import load_config

@click.group()
def cli():
    """codegraphy: Codebase knowledge graph & MCP server."""
    load_config()

@cli.command()
@click.option('--db', help='Database URL (e.g. postgresql://localhost/codegraphy)')
def init(db):
    """Initialize the database schema."""
    import repolens.config as config
    from repolens.db.store import Store
    
    db_url = db or config.DATABASE_URL
    click.echo(f"Initializing schema for {db_url}...")
    store = Store(db_url)
    store.init_schema()
    click.echo("Schema initialized.")

@cli.command()
@click.argument('path', default='.')
@click.option('--exclude', help='Comma-separated list of directories to exclude')
def index(path, exclude):
    """Index a directory into the graph."""
    import repolens.config as config
    from repolens.db.store import Store
    from repolens.indexer.walker import index_path
    
    click.echo(f"Indexing {path}...")
    store = Store(config.DATABASE_URL)
    exclude_list = exclude.split(',') if exclude else None
    
    # Load plugins
    plugins = [] # TODO: instantiate from config.REPOLENS_PLUGINS
    
    count = index_path(path, store, plugins, exclude_list)
    click.echo(f"Indexed {count} files.")

@cli.command()
def update():
    """Update index incrementally based on git diff."""
    import subprocess
    import repolens.config as config
    from repolens.db.store import Store
    from repolens.indexer.walker import index_path
    
    click.echo("Updating index...")
    try:
        res = subprocess.run(['git', 'diff', '--name-only', 'HEAD'], capture_output=True, text=True)
        changed_files = res.stdout.splitlines()
    except Exception:
        click.echo("Not a git repository or no HEAD.")
        return
        
    store = Store(config.DATABASE_URL)
    plugins = [] # TODO
    
    count = 0
    for file_path in changed_files:
        # Instead of calling index_path, we should just index the specific files
        # Re-using index_path is tricky since it takes a root.
        # We can just write a small loop here for the changed files.
        import os
        from repolens.indexer.walker import INDEXERS, sha256
        
        path = os.path.abspath(file_path)
        if not os.path.exists(path):
            continue
            
        indexer = next((i for i in INDEXERS if i.can_handle(path)), None)
        if not indexer:
            continue
            
        try:
            with open(path, 'rb') as f:
                content_bytes = f.read()
            file_hash = sha256(content_bytes)
            if store.get_file_hash(path) == file_hash:
                continue
            
            content_str = content_bytes.decode('utf-8', errors='replace')
            symbols, edges = indexer.index_file(path, content_str)
            
            for plugin in plugins:
                symbols = [plugin.on_symbol(s) for s in symbols]
                edges.extend(plugin.extra_edges(symbols))
                
            store.upsert_file(path, file_hash, symbols, edges)
            count += 1
        except Exception:
            pass
            
    click.echo(f"Updated {count} files.")

@cli.command()
def serve():
    """Start the MCP server over stdio."""
    from repolens.mcp.server import start_server
    click.echo("Starting MCP server...", err=True)
    start_server()

@cli.command()
@click.argument('name')
def search(name):
    """Search for a symbol in the graph."""
    from repolens.mcp.server import search_symbol
    results = search_symbol(name)
    for res in results:
        click.echo(f"[{res['source']}] {res.get('qualified_name') or res.get('file_path')} - {res.get('kind', 'grep')} @ {res['line_start']}")

@cli.command()
@click.argument('name')
def usages(name):
    """Find usages of a symbol."""
    from repolens.mcp.server import find_usages
    results = find_usages(name)
    for res in results:
        click.echo(f"[{res['source']}] {res.get('from_qualified') or res.get('file_path')} - {res.get('relation', 'grep')} @ {res['line_start']}")

@cli.command()
def stats():
    """Show graph statistics."""
    from repolens.db.store import Store
    import repolens.config as config
    store = Store(config.DATABASE_URL)
    with store.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cg_files")
        files = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cg_symbols")
        symbols = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cg_edges")
        edges = cursor.fetchone()[0]
        click.echo(f"Files: {files}")
        click.echo(f"Symbols: {symbols}")
        click.echo(f"Edges: {edges}")

if __name__ == '__main__':
    cli()
