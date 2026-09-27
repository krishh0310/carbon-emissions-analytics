"""v2: state x sector emissions, sector forecasts, ATAR insights, scenarios

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SECTOR_CHECK = "sector IN ('POWER','TRANSPORT','INDUSTRY','BUILDINGS','AGRICULTURE','WASTE','OTHER')"


def _json():
    return postgresql.JSONB() if op.get_bind().dialect.name == "postgresql" else sa.JSON()


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = set(insp.get_table_names())  # 0001 used metadata.create_all, which may already include v2 tables
    if "emissions_state_sector" not in have:
        op.create_table(
            "emissions_state_sector",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("state_code", sa.String(5), sa.ForeignKey("states.code"), nullable=False, index=True),
            sa.Column("sector", sa.String(12), nullable=False, index=True),
            sa.Column("year", sa.Integer, nullable=False),
            sa.Column("co2e_mt", sa.Float, nullable=False),
            sa.Column("co2_mt", sa.Float), sa.Column("ch4_co2e_mt", sa.Float), sa.Column("n2o_co2e_mt", sa.Float),
            sa.Column("source", sa.String(40), nullable=False), sa.Column("method", sa.String(160), nullable=False),
            sa.Column("confidence", sa.String(2), nullable=False),
            sa.UniqueConstraint("state_code", "sector", "year"),
            sa.CheckConstraint(SECTOR_CHECK, name="ck_ess_sector"),
        )
    if "forecasts_sector" not in have:
        op.create_table(
            "forecasts_sector",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("model_id", sa.Integer, sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("state_code", sa.String(5), sa.ForeignKey("states.code"), nullable=False, index=True),
            sa.Column("sector", sa.String(12), nullable=False, index=True),
            sa.Column("target", sa.String(20), nullable=False),
            sa.Column("year", sa.Integer, nullable=False),
            sa.Column("p10", sa.Float, nullable=False), sa.Column("p50", sa.Float, nullable=False),
            sa.Column("p90", sa.Float, nullable=False), sa.Column("p50_reconciled", sa.Float),
            sa.CheckConstraint(SECTOR_CHECK, name="ck_fs_sector"),
        )
    if "insights" not in have:
        op.create_table(
            "insights",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("state_code", sa.String(5), sa.ForeignKey("states.code"), index=True),
            sa.Column("sector", sa.String(12), index=True),
            sa.Column("type", sa.String(20), nullable=False, index=True),
            sa.Column("severity", sa.String(8), nullable=False, index=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text, nullable=False),
            sa.Column("evidence", _json()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "scenarios" not in have:
        op.create_table(
            "scenarios",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("params", _json()), sa.Column("results", _json()),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    for t in ("scenarios", "insights", "forecasts_sector", "emissions_state_sector"):
        op.drop_table(t)
