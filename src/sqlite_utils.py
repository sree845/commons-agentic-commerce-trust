
import sqlite3


class ClosingSQLiteConnection(sqlite3.Connection):
    """SQLite connection that closes after a with-block."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(
                exc_type,
                exc_value,
                traceback
            )
        finally:
            self.close()


def connect_sqlite(db_path, timeout=10):
    connection = sqlite3.connect(
        str(db_path),
        timeout=timeout,
        factory=ClosingSQLiteConnection
    )
    connection.row_factory = sqlite3.Row
    return connection
