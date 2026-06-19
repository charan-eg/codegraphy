import os
import hashlib
import subprocess
from .python import PythonIndexer
from ..db.store import Store

INDEXERS = [PythonIndexer()]

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

def index_path(root: str, store: Store, plugins: list, exclude: list[str] = None):
    exclude = exclude or ['.git', 'node_modules', '__pycache__', '.venv']
    files = get_files_to_index(root, exclude)
    
    indexed_count = 0
    for path in files:
        indexer = next((i for i in INDEXERS if i.can_handle(path)), None)
        if not indexer:
            continue
            
        try:
            with open(path, 'rb') as f:
                content_bytes = f.read()
        except OSError:
            continue
            
        file_hash = sha256(content_bytes)
        
        # Check if unchanged
        if store.get_file_hash(path) == file_hash:
            continue
            
        content_str = content_bytes.decode('utf-8', errors='replace')
        symbols, edges = indexer.index_file(path, content_str)
        
        # Apply plugins
        for plugin in plugins:
            symbols = [plugin.on_symbol(s) for s in symbols]
            edges.extend(plugin.extra_edges(symbols))
            
        store.upsert_file(path, file_hash, symbols, edges)
        indexed_count += 1
        
    return indexed_count
