import os
import hashlib
import subprocess
from .python import PythonIndexer
from ..db.store import Store

INDEXERS = [PythonIndexer()]
DEFAULT_EXCLUDE = [
    '.git',
    'node_modules',
    '__pycache__',
    '.venv',
    'dist',
    'build',
    '.tox',
    '.pytest_cache',
    'migrations',
]

def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def get_files_to_index(root: str, exclude: list[str]) -> list[str]:
    # Use git ls-files if possible
    try:
        result = subprocess.run(
            ['git', 'ls-files'],
            cwd=root,
            capture_output=True,
            text=True,
            check=True
        )
        files = result.stdout.splitlines()
        # Make paths absolute
        files = [os.path.join(root, f) for f in files]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to os.walk
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            # rudimentary exclude
            dirnames[:] = [d for d in dirnames if d not in exclude and not d.startswith('.')]
            for f in filenames:
                files.append(os.path.join(dirpath, f))
    
    # Filter excludes
    if exclude:
        filtered = []
        for f in files:
            if not any(ex in f for ex in exclude):
                filtered.append(f)
        files = filtered
        
    return files

def index_files(files: list[str], store: Store, plugins: list, progress_callback=None):
    indexed_count = 0
    if not files:
        return indexed_count

    with store.get_connection() as conn:
        existing_hashes = store.get_file_hashes(files, conn=conn)

        total_files = len(files)
        for scanned_count, path in enumerate(files, start=1):
            indexer = next((i for i in INDEXERS if i.can_handle(path)), None)
            if not indexer:
                if progress_callback:
                    progress_callback(path, scanned_count, indexed_count, total_files)
                continue

            try:
                with open(path, 'rb') as f:
                    content_bytes = f.read()
            except OSError:
                if progress_callback:
                    progress_callback(path, scanned_count, indexed_count, total_files)
                continue

            file_hash = sha256(content_bytes)
            if existing_hashes.get(path) == file_hash:
                if progress_callback:
                    progress_callback(path, scanned_count, indexed_count, total_files)
                continue

            content_str = content_bytes.decode('utf-8', errors='replace')
            symbols, edges = indexer.index_file(path, content_str)

            for plugin in plugins:
                symbols = [plugin.on_symbol(s) for s in symbols]
                edges.extend(plugin.extra_edges(symbols))

            store.upsert_file(path, file_hash, symbols, edges, conn=conn)
            existing_hashes[path] = file_hash
            indexed_count += 1

            if progress_callback:
                progress_callback(path, scanned_count, indexed_count, total_files)

    return indexed_count

def index_path(root: str, store: Store, plugins: list, exclude: list[str] = None, progress_callback=None):
    exclude = exclude or DEFAULT_EXCLUDE
    files = get_files_to_index(root, exclude)
    return index_files(files, store, plugins, progress_callback=progress_callback)
