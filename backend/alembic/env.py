import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so Alembic can detect them
from app.models.inventory import Base as InventoryBase
from app.models.booking   import Base as BookingBase

config  = context.config
target_metadata = InventoryBase.metadata

# Pull DB URL from environment (overrides alembic.ini)
db_url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL", "")
if db_url.startswith("postgresql+asyncpg"):
    db_url = db_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name:
    fileConfig(config.config_file_name)


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
