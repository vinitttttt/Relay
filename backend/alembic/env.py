from logging.config import fileConfig
import logging

from alembic import context
from app.core.config import get_database_url
from app.db.base import Base
from app.db.session import create_database_engine
from app.core.logging import log_exception
import app.models  # noqa: F401 - register all model tables on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
migration_logger = logging.getLogger("relay.migrations")


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_database_engine(get_database_url())
    try:
        with connectable.connect() as connection:
            sqlite_foreign_keys_disabled = connection.dialect.name == "sqlite"
            try:
                if sqlite_foreign_keys_disabled:
                    # SQLite table rebuilds otherwise cascade-delete child rows
                    # when batch mode replaces a referenced parent table.
                    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                    connection.commit()
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    compare_type=True,
                )

                with context.begin_transaction():
                    context.run_migrations()
            finally:
                if sqlite_foreign_keys_disabled:
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                    connection.commit()
    except Exception as exc:
        log_exception(migration_logger, "migration.failed", exc)
        raise
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
