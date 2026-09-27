"""v3: model registry columns (champion/challenger, shadow mode), insight moderation, serving log

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _has(table, col):
    return col in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for name, col in (("level", sa.Column("level", sa.String(16), server_default="state", nullable=False)),
                      ("status", sa.Column("status", sa.String(12), server_default="candidate", nullable=False)),
                      ("val_score", sa.Column("val_score", sa.Float)),
                      ("pinned", sa.Column("pinned", sa.Boolean, server_default=sa.false(), nullable=False)),
                      ("shadow_until", sa.Column("shadow_until", sa.DateTime(timezone=True))),
                      ("created_at", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))):
        if not _has("models", name):
            op.add_column("models", col)
    for name, col in (("approved", sa.Column("approved", sa.Boolean, server_default=sa.true(), nullable=False)),
                      ("admin_note", sa.Column("admin_note", sa.Text)),
                      ("edited_by", sa.Column("edited_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"))),
                      ("title_hi", sa.Column("title_hi", sa.String(240))),
                      ("body_hi", sa.Column("body_hi", sa.Text))):
        if not _has("insights", name):
            op.add_column("insights", col)
    if "serving_log" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("serving_log",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("model_id", sa.Integer, sa.ForeignKey("models.id", ondelete="CASCADE"), index=True),
                        sa.Column("role", sa.String(12), nullable=False),  # champion | challenger
                        sa.Column("endpoint", sa.String(60), nullable=False),
                        sa.Column("day", sa.Date, nullable=False, index=True),
                        sa.Column("n", sa.Integer, nullable=False, server_default="0"),
                        sa.UniqueConstraint("model_id", "endpoint", "day"))
    if "drift_reports" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("drift_reports",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
                        sa.Column("level", sa.String(16), nullable=False),
                        sa.Column("psi_max", sa.Float), sa.Column("mase_drift", sa.Float),
                        sa.Column("triggered", sa.Boolean, nullable=False, server_default=sa.false()),
                        sa.Column("details", sa.JSON))


def downgrade() -> None:
    op.drop_table("drift_reports")
    op.drop_table("serving_log")
    for c in ("title_hi", "body_hi", "edited_by", "admin_note", "approved"):
        op.drop_column("insights", c)
    for c in ("created_at", "shadow_until", "pinned", "val_score", "status", "level"):
        op.drop_column("models", c)
