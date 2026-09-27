"""initial schema (PostGIS)

Revision ID: 0001
"""
from alembic import op

from backend.app.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    # Baseline = the ORM metadata at v1.0 (v2 tables are created by 0002).
    v2 = {"emissions_state_sector", "forecasts_sector", "insights", "scenarios", "serving_log", "drift_reports"}
    Base.metadata.create_all(bind, tables=[t for n, t in Base.metadata.tables.items() if n not in v2])


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
