from dataclasses import dataclass, field

@dataclass
class Symbol:
    name: str
    qualified_name: str
    kind: str
    file_path: str
    line_start: int
    line_end: int
    summary: str = ""
    raw_signature: str = ""
    extra: dict = field(default_factory=dict)

@dataclass
class Edge:
    from_qualified: str
    to_qualified: str
    relation: str

class BaseIndexer:
    def can_handle(self, file_path: str) -> bool:
        raise NotImplementedError

    def index_file(self, file_path: str, source: str) -> tuple[list[Symbol], list[Edge]]:
        """Returns symbols and edges found in the file."""
        raise NotImplementedError
