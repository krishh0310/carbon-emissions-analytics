from alembic import context

from backend.app.config import settings
from backend.app.db import Base, engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine().connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
