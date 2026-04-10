"""Integration tests for Row-Level Security (RLS) policies.

Tests verify that RLS is enabled on all tables and that setting
app.current_tenant_id restricts row visibility per tenant.
Runs against the real local PostgreSQL test database.
"""

import uuid

import asyncpg
import pytest

pytestmark = pytest.mark.integration

RAW_TEST_DB_URL = "postgresql://postgres:devpass@localhost:5435/workflows_test"


@pytest.fixture
async def migrated_db():
    """Run Alembic migrations on the test database, yield pool, then downgrade."""
    import os
    import subprocess

    env = os.environ.copy()
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:devpass@localhost:5435/workflows_test"
    )

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        env=env,
    )
    assert result.returncode == 0, f"Alembic upgrade failed: {result.stderr}"

    pool = await asyncpg.create_pool(RAW_TEST_DB_URL)
    yield pool
    await pool.close()

    subprocess.run(
        ["alembic", "downgrade", "base"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        env=env,
    )


async def _create_tenant(conn, name: str = "Test Tenant") -> uuid.UUID:
    """Helper: insert a tenant and return its id."""
    tenant_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
        "VALUES ($1, $2, $3, $4)",
        tenant_id,
        name,
        f"hash_{tenant_id.hex[:8]}",
        f"pre_{tenant_id.hex[:8]}",
    )
    return tenant_id


async def _create_workflow(conn, tenant_id: uuid.UUID) -> uuid.UUID:
    """Helper: insert a workflow and return its id."""
    wf_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflows (id, tenant_id, name, trigger_type, steps) "
        "VALUES ($1, $2, $3, $4, $5)",
        wf_id,
        tenant_id,
        "Test Workflow",
        "webhook",
        "[]",
    )
    return wf_id


async def _create_execution(
    conn, tenant_id: uuid.UUID, workflow_id: uuid.UUID
) -> uuid.UUID:
    """Helper: insert an execution and return its id."""
    exec_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO executions (id, tenant_id, workflow_id) "
        "VALUES ($1, $2, $3)",
        exec_id,
        tenant_id,
        workflow_id,
    )
    return exec_id


class TestRLSEnabled:
    """Tests that RLS is enabled on all tables."""

    async def test_rls_enabled_on_tenants(self, migrated_db):
        """RLS is enabled on the tenants table."""
        async with migrated_db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT rowsecurity FROM pg_tables "
                "WHERE tablename = 'tenants' AND schemaname = 'public'"
            )
        assert result is True

    async def test_rls_enabled_on_workflows(self, migrated_db):
        """RLS is enabled on the workflows table."""
        async with migrated_db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT rowsecurity FROM pg_tables "
                "WHERE tablename = 'workflows' AND schemaname = 'public'"
            )
        assert result is True

    async def test_rls_enabled_on_executions(self, migrated_db):
        """RLS is enabled on the executions table."""
        async with migrated_db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT rowsecurity FROM pg_tables "
                "WHERE tablename = 'executions' AND schemaname = 'public'"
            )
        assert result is True

    async def test_rls_enabled_on_step_executions(self, migrated_db):
        """RLS is enabled on the step_executions table."""
        async with migrated_db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT rowsecurity FROM pg_tables "
                "WHERE tablename = 'step_executions' AND schemaname = 'public'"
            )
        assert result is True

    async def test_rls_enabled_on_execution_logs(self, migrated_db):
        """RLS is enabled on the execution_logs table."""
        async with migrated_db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT rowsecurity FROM pg_tables "
                "WHERE tablename = 'execution_logs' AND schemaname = 'public'"
            )
        assert result is True

    async def test_rls_enabled_on_webhook_deliveries(self, migrated_db):
        """RLS is enabled on the webhook_deliveries table."""
        async with migrated_db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT rowsecurity FROM pg_tables "
                "WHERE tablename = 'webhook_deliveries' AND schemaname = 'public'"
            )
        assert result is True


class TestRLSPoliciesExist:
    """Tests that RLS policies are created on all tables."""

    async def test_policy_exists_on_tenants(self, migrated_db):
        """An RLS policy exists on the tenants table."""
        async with migrated_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_policies "
                "WHERE tablename = 'tenants' AND schemaname = 'public'"
            )
        assert count > 0

    async def test_policy_exists_on_workflows(self, migrated_db):
        """An RLS policy exists on the workflows table."""
        async with migrated_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_policies "
                "WHERE tablename = 'workflows' AND schemaname = 'public'"
            )
        assert count > 0

    async def test_policy_exists_on_executions(self, migrated_db):
        """An RLS policy exists on the executions table."""
        async with migrated_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_policies "
                "WHERE tablename = 'executions' AND schemaname = 'public'"
            )
        assert count > 0

    async def test_policy_exists_on_step_executions(self, migrated_db):
        """An RLS policy exists on the step_executions table."""
        async with migrated_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_policies "
                "WHERE tablename = 'step_executions' AND schemaname = 'public'"
            )
        assert count > 0

    async def test_policy_exists_on_execution_logs(self, migrated_db):
        """An RLS policy exists on the execution_logs table."""
        async with migrated_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_policies "
                "WHERE tablename = 'execution_logs' AND schemaname = 'public'"
            )
        assert count > 0

    async def test_policy_exists_on_webhook_deliveries(self, migrated_db):
        """An RLS policy exists on the webhook_deliveries table."""
        async with migrated_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_policies "
                "WHERE tablename = 'webhook_deliveries' AND schemaname = 'public'"
            )
        assert count > 0


class TestRLSTenantIsolation:
    """Tests that RLS policies enforce tenant isolation.

    NOTE: RLS policies don't apply to superusers (like the postgres user).
    We need a non-superuser role to test isolation. The migration creates
    an 'app_user' role for this purpose.
    """

    async def _setup_app_user_conn(self, migrated_db):
        """Create connection as app_user with a specific tenant_id set."""
        # We connect as postgres (superuser) to set up data,
        # then test RLS using a separate connection with app_user role.
        return migrated_db

    async def test_rls_tenants_isolates_by_tenant_id(self, migrated_db):
        """Tenants table RLS restricts SELECT to matching tenant."""
        async with migrated_db.acquire() as conn:
            tenant_a = await _create_tenant(conn, "Tenant A")
            tenant_b = await _create_tenant(conn, "Tenant B")

            # Create app_user role if not exists and grant permissions
            await conn.execute(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') "
                "THEN CREATE ROLE app_user LOGIN; END IF; END $$"
            )
            await conn.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO app_user")

        # Connect as app_user to test RLS
        app_url = RAW_TEST_DB_URL.replace("postgres:", "app_user:")
        try:
            app_conn = await asyncpg.connect(app_url)
        except asyncpg.InvalidPasswordError:
            # If password auth is required, set it
            async with migrated_db.acquire() as conn:
                await conn.execute(
                    "ALTER ROLE app_user WITH PASSWORD 'app_user_pass' LOGIN"
                )
            app_url = "postgresql://app_user:app_user_pass@localhost:5435/workflows_test"
            app_conn = await asyncpg.connect(app_url)

        try:
            # Set tenant context to Tenant A
            await app_conn.execute(
                f"SET app.current_tenant_id = '{tenant_a}'"
            )
            rows = await app_conn.fetch("SELECT id FROM tenants")
            tenant_ids = {r["id"] for r in rows}
            assert tenant_a in tenant_ids
            assert tenant_b not in tenant_ids
        finally:
            await app_conn.close()

    async def test_rls_workflows_isolates_by_tenant_id(self, migrated_db):
        """Workflows table RLS restricts SELECT to matching tenant."""
        async with migrated_db.acquire() as conn:
            tenant_a = await _create_tenant(conn, "Tenant A")
            tenant_b = await _create_tenant(conn, "Tenant B")
            wf_a = await _create_workflow(conn, tenant_a)
            wf_b = await _create_workflow(conn, tenant_b)

            await conn.execute(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') "
                "THEN CREATE ROLE app_user LOGIN; END IF; END $$"
            )
            await conn.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO app_user")

        app_url = RAW_TEST_DB_URL.replace("postgres:", "app_user:")
        try:
            app_conn = await asyncpg.connect(app_url)
        except asyncpg.InvalidPasswordError:
            async with migrated_db.acquire() as conn:
                await conn.execute(
                    "ALTER ROLE app_user WITH PASSWORD 'app_user_pass' LOGIN"
                )
            app_url = "postgresql://app_user:app_user_pass@localhost:5435/workflows_test"
            app_conn = await asyncpg.connect(app_url)

        try:
            await app_conn.execute(
                f"SET app.current_tenant_id = '{tenant_a}'"
            )
            rows = await app_conn.fetch("SELECT id FROM workflows")
            workflow_ids = {r["id"] for r in rows}
            assert wf_a in workflow_ids
            assert wf_b not in workflow_ids
        finally:
            await app_conn.close()

    async def test_rls_executions_isolates_by_tenant_id(self, migrated_db):
        """Executions table RLS restricts SELECT to matching tenant."""
        async with migrated_db.acquire() as conn:
            tenant_a = await _create_tenant(conn, "Tenant A")
            tenant_b = await _create_tenant(conn, "Tenant B")
            wf_a = await _create_workflow(conn, tenant_a)
            wf_b = await _create_workflow(conn, tenant_b)
            exec_a = await _create_execution(conn, tenant_a, wf_a)
            exec_b = await _create_execution(conn, tenant_b, wf_b)

            await conn.execute(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') "
                "THEN CREATE ROLE app_user LOGIN; END IF; END $$"
            )
            await conn.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO app_user")

        app_url = RAW_TEST_DB_URL.replace("postgres:", "app_user:")
        try:
            app_conn = await asyncpg.connect(app_url)
        except asyncpg.InvalidPasswordError:
            async with migrated_db.acquire() as conn:
                await conn.execute(
                    "ALTER ROLE app_user WITH PASSWORD 'app_user_pass' LOGIN"
                )
            app_url = "postgresql://app_user:app_user_pass@localhost:5435/workflows_test"
            app_conn = await asyncpg.connect(app_url)

        try:
            await app_conn.execute(
                f"SET app.current_tenant_id = '{tenant_a}'"
            )
            rows = await app_conn.fetch("SELECT id FROM executions")
            exec_ids = {r["id"] for r in rows}
            assert exec_a in exec_ids
            assert exec_b not in exec_ids
        finally:
            await app_conn.close()
