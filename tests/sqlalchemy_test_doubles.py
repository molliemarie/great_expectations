from contextlib import contextmanager
from typing import Any


class MockSaInspector:
    def get_columns(self) -> list[dict[str, Any]]:  # type: ignore[empty-body]
        ...

    def get_schema_names(self) -> list[str]:  # type: ignore[empty-body]
        ...

    def has_table(self, table_name: str, schema: str) -> bool:  # type: ignore[empty-body]
        ...


class Dialect:
    def __init__(self, dialect: str):
        self.name = dialect


class _MockConnection:
    def __init__(self, dialect: Dialect):
        self.dialect = dialect

    @contextmanager
    def begin(self):
        yield _MockConnection(self.dialect)

    def execute(self, statement):
        self.statement = statement
        return


class MockSaEngine:
    def __init__(self, dialect: Dialect):
        self.dialect = dialect

    @contextmanager
    def begin(self):
        yield _MockConnection(self.dialect)

    @contextmanager
    def connect(self):
        """A contextmanager that yields a _MockConnection"""
        yield _MockConnection(self.dialect)
