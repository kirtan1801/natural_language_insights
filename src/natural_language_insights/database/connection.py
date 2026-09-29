from pathlib import Path

import duckdb


class DuckDBManager:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._connection: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> None:
        if self._connection is None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = duckdb.connect(str(self.database_path))

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._connection is None:
            raise RuntimeError("DuckDB connection is not initialized.")
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
