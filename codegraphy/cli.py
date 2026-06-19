import click
from .config import load_config
import time

def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(seconds, 60)
    return f"{int(minutes)}m {remaining:.1f}s"

def _run_with_progress(label: str, files: list[str], runner):
    total_files = len(files)
    start = time.monotonic()

    if total_files == 0:
        click.echo(f"{label}...")
        click.echo("Scanned 0 files, indexed 0 files in 0.0s.")
        return 0

    with click.progressbar(length=total_files, label=label, show_eta=True, show_percent=True) as bar:
        def progress_callback(path, scanned_count, indexed_count, total_count):
            bar.update(scanned_count - bar.pos)

        indexed_count = runner(progress_callback)

    elapsed = _format_elapsed(time.monotonic() - start)
    click.echo(f"Scanned {total_files} files, indexed {indexed_count} files in {elapsed}.")
    return indexed_count

@click.group()
def cli():
    """codegraphy: Codebase knowledge graph & MCP server."""
    load_config()

@cli.command()
@click.option('--db', help='Database URL (e.g. postgresql://localhost/codegraphy)')
def init(db):
    """Initialize the database schema."""
    import codegraphy.config as config
    from codegraphy.db.store import Store
    
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
    import codegraphy.config as config
    from codegraphy.db.store import Store
    from codegraphy.indexer.walker import DEFAULT_EXCLUDE, get_files_to_index, index_files

    store = Store(config.DATABASE_URL)
    exclude_list = exclude.split(',') if exclude else DEFAULT_EXCLUDE
    files = get_files_to_index(path, exclude_list)

    # Load plugins
    plugins = [] # TODO: instantiate from config.CODEGRAPHY_PLUGINS

    _run_with_progress(
        f"Indexing {path}",
        files,
        lambda progress_callback: index_files(files, store, plugins, progress_callback=progress_callback),
    )

@cli.command()
def update():
    """Update index incrementally based on git diff."""
    import subprocess
    import os
    import codegraphy.config as config
    from codegraphy.db.store import Store
    from codegraphy.indexer.walker import index_files
    
    try:
        res = subprocess.run(['git', 'diff', '--name-only', 'HEAD'], capture_output=True, text=True)
        changed_files = res.stdout.splitlines()
    except Exception:
        click.echo("Not a git repository or no HEAD.")
        return
        
    store = Store(config.DATABASE_URL)
    plugins = [] # TODO

    paths = []
    for file_path in changed_files:
        path = os.path.join('.', file_path)
        if os.path.exists(path):
            paths.append(path)

    _run_with_progress(
        "Updating index",
        paths,
        lambda progress_callback: index_files(paths, store, plugins, progress_callback=progress_callback),
    )

@cli.command()
def serve():
    """Start the MCP server over stdio."""
    from codegraphy.mcp.server import prepare_server, start_server

    startup_steps = [
        "Loading MCP tool registry",
        "Connecting to graph database",
        "Starting stdio transport",
    ]
    server_info = None

    with click.progressbar(
        length=len(startup_steps),
        label="Starting MCP server",
        show_eta=False,
        show_percent=True,
        file=click.get_text_stream('stderr'),
    ) as bar:
        bar.update(1)
        server_info = prepare_server()
        bar.update(1)
        bar.update(1)

    click.echo(
        f"MCP server ready on stdio "
        f"(backend: {server_info['backend']}, files: {server_info['files']}, symbols: {server_info['symbols']}). "
        f"Waiting for client...",
        err=True,
    )
    start_server()

@cli.command()
@click.argument('name')
def search(name):
    """Search for a symbol in the graph."""
    from codegraphy.mcp.server import search_symbol
    results = search_symbol(name)
    for res in results:
        click.echo(f"[{res['source']}] {res.get('qualified_name') or res.get('file_path')} - {res.get('kind', 'grep')} @ {res['line_start']}")

@cli.command()
@click.argument('name')
def usages(name):
    """Find usages of a symbol."""
    from codegraphy.mcp.server import find_usages
    results = find_usages(name)
    for res in results:
        click.echo(f"[{res['source']}] {res.get('from_qualified') or res.get('file_path')} - {res.get('relation', 'grep')} @ {res['line_start']}")

@cli.command()
def stats():
    """Show graph statistics."""
    from codegraphy.db.store import Store
    import codegraphy.config as config
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
