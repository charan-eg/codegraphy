import ast
import os
from .base import BaseIndexer, Symbol, Edge

def _get_module_path(file_path: str) -> str:
    # Basic conversion from file path to dotted module path
    # e.g., src/foo/bar.py -> src.foo.bar
    # This is a simple approximation.
    base = os.path.splitext(file_path)[0]
    return base.replace(os.sep, '.')

class PythonIndexer(BaseIndexer):
    def can_handle(self, file_path: str) -> bool:
        return file_path.endswith('.py')

    def index_file(self, file_path: str, source: str) -> tuple[list[Symbol], list[Edge]]:
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return [], []

        module_path = _get_module_path(file_path)
        
        symbols = []
        edges = []
        
        # We need a visitor to traverse the AST.
        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.current_scope = []
                self.current_class = None

            def _get_dotted_name(self, node):
                if isinstance(node, ast.Name):
                    return node.id
                elif isinstance(node, ast.Attribute):
                    val = self._get_dotted_name(node.value)
                    if val:
                        return f"{val}.{node.attr}"
                return None

            def get_qualname(self, name):
                if not self.current_scope:
                    return f"{module_path}.{name}" if module_path else name
                return f"{module_path}.{'.'.join(self.current_scope)}.{name}"

            def get_import_qualname(self, node, imported_name, source_module):
                scope = ".".join(self.current_scope)
                parts = [module_path] if module_path else []
                if scope:
                    parts.append(scope)
                parts.extend(["__import__", str(node.lineno), str(node.col_offset), source_module, imported_name])
                return ".".join(parts)

            def visit_ClassDef(self, node):
                qualname = self.get_qualname(node.name)
                summary = ast.get_docstring(node) or ""
                if summary:
                    summary = summary.splitlines()[0]
                
                symbols.append(Symbol(
                    name=node.name,
                    qualified_name=qualname,
                    kind="class",
                    file_path=file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno,
                    summary=summary
                ))
                
                # Inherits edges
                for base in node.bases:
                    target = self._get_dotted_name(base)
                    if target:
                        edges.append(Edge(
                            from_qualified=qualname,
                            to_qualified=target, # Approximated base name
                            relation="inherits"
                        ))

                self.current_scope.append(node.name)
                prev_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = prev_class
                self.current_scope.pop()

            def visit_FunctionDef(self, node):
                self._visit_func(node)
            def visit_AsyncFunctionDef(self, node):
                self._visit_func(node)

            def _visit_func(self, node):
                qualname = self.get_qualname(node.name)
                summary = ast.get_docstring(node) or ""
                if summary:
                    summary = summary.splitlines()[0]
                
                kind = "method" if self.current_class else "function"
                
                symbols.append(Symbol(
                    name=node.name,
                    qualified_name=qualname,
                    kind=kind,
                    file_path=file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno,
                    summary=summary
                ))
                
                self.current_scope.append(node.name)
                self.generic_visit(node)
                self.current_scope.pop()

            def visit_Import(self, node):
                for alias in node.names:
                    # module level import
                    # e.g., import os
                    qualname = self.get_import_qualname(node, alias.asname or alias.name, alias.name)
                    symbols.append(Symbol(
                        name=alias.asname or alias.name,
                        qualified_name=qualname,
                        kind="import",
                        file_path=file_path,
                        line_start=node.lineno,
                        line_end=node.end_lineno,
                        extra={"module": alias.name}
                    ))
                    
                    edges.append(Edge(
                        from_qualified=module_path,
                        to_qualified=alias.name,
                        relation="imports"
                    ))

            def visit_ImportFrom(self, node):
                if node.module:
                    for alias in node.names:
                        name = alias.asname or alias.name
                        qualname = self.get_import_qualname(node, name, node.module)
                        symbols.append(Symbol(
                            name=name,
                            qualified_name=qualname,
                            kind="import",
                            file_path=file_path,
                            line_start=node.lineno,
                            line_end=node.end_lineno,
                            extra={"module": node.module, "original_name": alias.name}
                        ))
                        
                        edges.append(Edge(
                            from_qualified=module_path,
                            to_qualified=f"{node.module}.{alias.name}",
                            relation="imports"
                        ))

            def visit_Call(self, node):
                # Extract simple calls
                target = self._get_dotted_name(node.func)
                    
                if target and self.current_scope:
                    caller = self.get_qualname("")[:-1] # strip trailing dot
                    edges.append(Edge(
                        from_qualified=caller,
                        to_qualified=target, # We don't have full res, will be resolved or approximated during usages query
                        relation="calls"
                    ))
                
                self.generic_visit(node)

        visitor = Visitor()
        visitor.visit(tree)
        
        # Add a symbol for the file itself
        symbols.append(Symbol(
            name=os.path.basename(file_path),
            qualified_name=module_path,
            kind="file",
            file_path=file_path,
            line_start=1,
            line_end=len(source.splitlines()),
            summary=""
        ))
        
        return symbols, edges
