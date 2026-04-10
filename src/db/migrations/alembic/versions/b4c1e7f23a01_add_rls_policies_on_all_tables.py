"""add RLS policies on all tables

Revision ID: b4c1e7f23a01
Revises: fa83d4b59092
Create Date: 2026-04-10 22:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c1e7f23a01"
down_revision: str | None = "fa83d4b59092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that use tenant_id column for RLS filtering
_TENANT_ID_TABLES = [
    "workflows",
    "executions",
    "step_executions",
    "execution_logs",
    "webhook_deliveries",
]


def upgrade() -> None:
    # Create app_user role if it does not exist (used by the application)
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') "
        "THEN CREATE ROLE app_user LOGIN PASSWORD 'app_user_pass'; "
        "END IF; END $$"
    )
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO app_user")

    # Enable RLS on tenants table (uses id, not tenant_id)
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_policy ON tenants "
        "FOR ALL "
        "USING (id = current_setting('app.current_tenant_id')::uuid)"
    )

    # Enable RLS on all other tables (use tenant_id column)
    for table in _TENANT_ID_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_policy ON {table} "
            f"FOR ALL "
            f"USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
        )


def downgrade() -> None:
    # Drop RLS policies and disable RLS on all tables
    for table in _TENANT_ID_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")

    # Revoke app_user grants (role itself is kept for safety)
    op.execute(
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_user"
    )
