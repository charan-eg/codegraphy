from ..indexer.base import Symbol, Edge

class BasePlugin:
    def on_symbol(self, symbol: Symbol) -> Symbol:
        """Mutate or re-tag a symbol. Return unchanged if not applicable."""
        return symbol

    def extra_edges(self, symbols: list[Symbol]) -> list[Edge]:
        """Derive extra edges from the full symbol list after file is indexed."""
        return []
