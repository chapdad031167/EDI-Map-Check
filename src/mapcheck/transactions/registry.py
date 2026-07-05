"""Registry of transaction definitions.

Bundled definitions ship as YAML files next to this module
(``definitions/*.yaml``) and are discovered lazily. Tests and downstream
code can register additional definitions at runtime — that is the whole
plugin path: build a :class:`TransactionDefinition` (usually from YAML) and
call :meth:`TransactionRegistry.register`.
"""

from __future__ import annotations

from importlib import resources

from mapcheck.transactions.loader import load_definition, parse_definition
from mapcheck.transactions.schema import TransactionDefinition

import yaml


class UnknownTransactionError(KeyError):
    """Raised when no definition is registered for a transaction set."""

    def __init__(self, set_code: str, known: list[str]) -> None:
        self.set_code = set_code
        super().__init__(
            f"no transaction definition registered for ST01={set_code!r} "
            f"(registered: {', '.join(known) or 'none'})"
        )


class TransactionRegistry:
    """Maps ST01 transaction set codes to definitions."""

    def __init__(self) -> None:
        self._definitions: dict[str, TransactionDefinition] = {}
        self._bundled_loaded = False

    def _load_bundled(self) -> None:
        if self._bundled_loaded:
            return
        self._bundled_loaded = True
        package = resources.files("mapcheck.transactions") / "definitions"
        for entry in sorted(package.iterdir(), key=lambda e: e.name):
            if entry.name.endswith((".yaml", ".yml")):
                data = yaml.safe_load(entry.read_text(encoding="utf-8"))
                definition = parse_definition(data, source=f"bundled:{entry.name}")
                self._definitions.setdefault(definition.set_code, definition)

    def register(self, definition: TransactionDefinition, replace: bool = False) -> None:
        """Add a definition; refuses to shadow an existing one unless asked."""
        self._load_bundled()
        if not replace and definition.set_code in self._definitions:
            raise ValueError(
                f"transaction set {definition.set_code!r} is already registered "
                f"({self._definitions[definition.set_code].source}); pass replace=True"
            )
        self._definitions[definition.set_code] = definition

    def register_file(self, path: str, replace: bool = False) -> TransactionDefinition:
        """Load a YAML definition file and register it."""
        definition = load_definition(path)
        self.register(definition, replace=replace)
        return definition

    def get(self, set_code: str) -> TransactionDefinition:
        """Definition for an ST01 code; raises :class:`UnknownTransactionError`."""
        self._load_bundled()
        try:
            return self._definitions[set_code]
        except KeyError:
            raise UnknownTransactionError(set_code, sorted(self._definitions)) from None

    def all(self) -> list[TransactionDefinition]:
        """All registered definitions, ordered by set code."""
        self._load_bundled()
        return [self._definitions[key] for key in sorted(self._definitions)]


#: Process-wide registry used by the CLI, Streamlit, and validate_files.
default_registry = TransactionRegistry()
