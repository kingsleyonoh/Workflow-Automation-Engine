"""Integration tests for Alembic migrations — tenants and workflows tables.

Tests verify that tables exist, columns have correct types,
constraints are enforced, indexes exist, and FK relationships work.
Runs against the real local PostgreSQL test database.
"""

import uuid
from datetime import datetime

import asyncpg
import pytest

pytestmark = pytest.mark.integration

# Raw asyncpg URL for direct database access
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

    # Run migrations
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

    # Downgrade to clean up
    subprocess.run(
        ["alembic", "downgrade", "base"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        env=env,
    )


# ─── Tenants Table Tests ────────────────────────────────────────────


class TestTenantsTable:
    """Tests for the tenants table schema and constraints."""

    async def test_tenants_table_exists(self, migrated_db):
        """Tenants table is created by migration."""
        async with migrated_db.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'tenants')"
            )
        assert exists is True

    async def test_tenants_columns_exist(self, migrated_db):
        """All required columns exist with correct types."""
        async with migrated_db.acquire() as conn:
            columns = await conn.fetch(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'tenants' ORDER BY ordinal_position"
            )
        col_map = {r["column_name"]: r for r in columns}

        assert "id" in col_map
        assert "name" in col_map
        assert "api_key_hash" in col_map
        assert "api_key_prefix" in col_map
        assert "is_active" in col_map
        assert "created_at" in col_map
        assert "updated_at" in col_map

    async def test_tenants_id_is_uuid_pk(self, migrated_db):
        """id column is UUID type."""
        async with migrated_db.acquire() as conn:
            col = await conn.fetchrow(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'tenants' AND column_name = 'id'"
            )
        assert col["data_type"] == "uuid"

    async def test_tenants_name_not_null(self, migrated_db):
        """name column rejects NULL values."""
        tenant_id = uuid.uuid4()
        async with migrated_db.acquire() as conn:
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
                    "VALUES ($1, $2, $3, $4)",
                    tenant_id,
                    None,
                    "hash",
                    "prefix",
                )

    async def test_tenants_api_key_hash_not_null(self, migrated_db):
        """api_key_hash column rejects NULL values."""
        tenant_id = uuid.uuid4()
        async with migrated_db.acquire() as conn:
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
                    "VALUES ($1, $2, $3, $4)",
                    tenant_id,
                    "Test",
                    None,
                    "prefix",
                )

    async def test_tenants_api_key_prefix_unique(self, migrated_db):
        """api_key_prefix column enforces UNIQUE constraint."""
        async with migrated_db.acquire() as conn:
            await conn.execute(
                "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
                "VALUES ($1, $2, $3, $4)",
                uuid.uuid4(),
                "Tenant A",
                "hash_a",
                "wae_live",
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
                    "VALUES ($1, $2, $3, $4)",
                    uuid.uuid4(),
                    "Tenant B",
                    "hash_b",
                    "wae_live",
                )

    async def test_tenants_is_active_defaults_true(self, migrated_db):
        """is_active defaults to TRUE when not specified."""
        tenant_id = uuid.uuid4()
        async with migrated_db.acquire() as conn:
            await conn.execute(
                "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
                "VALUES ($1, $2, $3, $4)",
                tenant_id,
                "Test",
                "hash",
                f"pre_{tenant_id.hex[:4]}",
            )
            result = await conn.fetchval(
                "SELECT is_active FROM tenants WHERE id = $1", tenant_id
            )
        assert result is True

    async def test_tenants_created_at_default(self, migrated_db):
        """created_at defaults to current timestamp."""
        tenant_id = uuid.uuid4()
        async with migrated_db.acquire() as conn:
            await conn.execute(
                "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
                "VALUES ($1, $2, $3, $4)",
                tenant_id,
                "Test",
                "hash",
                f"pre_{tenant_id.hex[:4]}",
            )
            result = await conn.fetchval(
                "SELECT created_at FROM tenants WHERE id = $1", tenant_id
            )
        assert isinstance(result, datetime)

    async def test_tenants_updated_at_default(self, migrated_db):
        """updated_at defaults to current timestamp."""
        tenant_id = uuid.uuid4()
        async with migrated_db.acquire() as conn:
            await conn.execute(
                "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
                "VALUES ($1, $2, $3, $4)",
                tenant_id,
                "Test",
                "hash",
                f"pre_{tenant_id.hex[:4]}",
            )
            result = await conn.fetchval(
                "SELECT updated_at FROM tenants WHERE id = $1", tenant_id
            )
        assert isinstance(result, datetime)

    async def test_tenants_index_on_api_key_prefix(self, migrated_db):
        """UNIQUE INDEX exists on api_key_prefix."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'tenants'"
            )
        index_names = [r["indexname"] for r in indexes]
        assert any("api_key_prefix" in name for name in index_names)

    async def test_tenants_index_on_is_active(self, migrated_db):
        """INDEX exists on is_active."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'tenants'"
            )
        index_names = [r["indexname"] for r in indexes]
        assert any("is_active" in name for name in index_names)


# ─── Workflows Table Tests ──────────────────────────────────────────


class TestWorkflowsTable:
    """Tests for the workflows table schema and constraints."""

    async def _create_tenant(self, conn) -> uuid.UUID:
        """Helper: insert a tenant and return its id."""
        tenant_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO tenants (id, name, api_key_hash, api_key_prefix) "
            "VALUES ($1, $2, $3, $4)",
            tenant_id,
            "Test Tenant",
            "hash",
            f"pre_{tenant_id.hex[:8]}",
        )
        return tenant_id

    async def test_workflows_table_exists(self, migrated_db):
        """Workflows table is created by migration."""
        async with migrated_db.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'workflows')"
            )
        assert exists is True

    async def test_workflows_columns_exist(self, migrated_db):
        """All required columns exist."""
        async with migrated_db.acquire() as conn:
            columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'workflows'"
            )
        col_names = {r["column_name"] for r in columns}
        expected = {
            "id",
            "tenant_id",
            "name",
            "description",
            "trigger_type",
            "trigger_config",
            "steps",
            "is_active",
            "webhook_path",
            "webhook_secret",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(col_names)

    async def test_workflows_tenant_id_fk(self, migrated_db):
        """tenant_id FK references tenants.id."""
        async with migrated_db.acquire() as conn:
            # Insert workflow with non-existent tenant_id should fail
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO workflows "
                    "(id, tenant_id, name, trigger_type, steps) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    uuid.uuid4(),  # non-existent tenant
                    "Test WF",
                    "webhook",
                    "[]",
                )

    async def test_workflows_name_not_null(self, migrated_db):
        """name column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO workflows "
                    "(id, tenant_id, name, trigger_type, steps) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    None,
                    "webhook",
                    "[]",
                )

    async def test_workflows_trigger_type_not_null(self, migrated_db):
        """trigger_type column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO workflows "
                    "(id, tenant_id, name, trigger_type, steps) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    "Test WF",
                    None,
                    "[]",
                )

    async def test_workflows_steps_not_null(self, migrated_db):
        """steps column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO workflows "
                    "(id, tenant_id, name, trigger_type, steps) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    "Test WF",
                    "webhook",
                    None,
                )

    async def test_workflows_description_nullable(self, migrated_db):
        """description column accepts NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            wf_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO workflows "
                "(id, tenant_id, name, description, trigger_type, steps) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                wf_id,
                tenant_id,
                "Test WF",
                None,
                "webhook",
                "[]",
            )
            result = await conn.fetchval(
                "SELECT description FROM workflows WHERE id = $1", wf_id
            )
        assert result is None

    async def test_workflows_webhook_path_unique(self, migrated_db):
        """webhook_path enforces UNIQUE constraint."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            await conn.execute(
                "INSERT INTO workflows "
                "(id, tenant_id, name, trigger_type, steps, webhook_path) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                uuid.uuid4(),
                tenant_id,
                "WF A",
                "webhook",
                "[]",
                "/hooks/unique-path",
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO workflows "
                    "(id, tenant_id, name, trigger_type, steps, webhook_path) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    uuid.uuid4(),
                    tenant_id,
                    "WF B",
                    "webhook",
                    "[]",
                    "/hooks/unique-path",
                )

    async def test_workflows_trigger_config_defaults_empty_json(self, migrated_db):
        """trigger_config defaults to empty JSON object."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            wf_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO workflows "
                "(id, tenant_id, name, trigger_type, steps) "
                "VALUES ($1, $2, $3, $4, $5)",
                wf_id,
                tenant_id,
                "Test WF",
                "manual",
                "[]",
            )
            import json

            result = await conn.fetchval(
                "SELECT trigger_config::text FROM workflows WHERE id = $1", wf_id
            )
        assert json.loads(result) == {}

    async def test_workflows_is_active_defaults_true(self, migrated_db):
        """is_active defaults to TRUE."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            wf_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO workflows "
                "(id, tenant_id, name, trigger_type, steps) "
                "VALUES ($1, $2, $3, $4, $5)",
                wf_id,
                tenant_id,
                "Test WF",
                "manual",
                "[]",
            )
            result = await conn.fetchval(
                "SELECT is_active FROM workflows WHERE id = $1", wf_id
            )
        assert result is True

    async def test_workflows_created_at_default(self, migrated_db):
        """created_at defaults to current timestamp."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            wf_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO workflows "
                "(id, tenant_id, name, trigger_type, steps) "
                "VALUES ($1, $2, $3, $4, $5)",
                wf_id,
                tenant_id,
                "Test WF",
                "manual",
                "[]",
            )
            result = await conn.fetchval(
                "SELECT created_at FROM workflows WHERE id = $1", wf_id
            )
        assert isinstance(result, datetime)

    async def test_workflows_index_tenant_is_active(self, migrated_db):
        """Composite INDEX exists on (tenant_id, is_active)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'workflows'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "is_active" in defn for defn in index_defs.values()
        )

    async def test_workflows_index_tenant_trigger_type(self, migrated_db):
        """Composite INDEX exists on (tenant_id, trigger_type)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'workflows'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "trigger_type" in defn
            for defn in index_defs.values()
        )

    async def test_workflows_index_webhook_path(self, migrated_db):
        """INDEX exists on webhook_path."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'workflows'"
            )
        index_names = [r["indexname"] for r in indexes]
        assert any("webhook_path" in name for name in index_names)

    async def test_workflows_cascade_on_tenant_delete(self, migrated_db):
        """Deleting a tenant cascades to delete its workflows."""
        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            wf_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO workflows "
                "(id, tenant_id, name, trigger_type, steps) "
                "VALUES ($1, $2, $3, $4, $5)",
                wf_id,
                tenant_id,
                "Test WF",
                "manual",
                "[]",
            )
            # Delete the tenant
            await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
            # Workflow should be deleted too
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM workflows WHERE id = $1", wf_id
            )
        assert count == 0

    async def test_workflows_insert_happy_path(self, migrated_db):
        """Full workflow insert with all fields succeeds."""
        import json

        async with migrated_db.acquire() as conn:
            tenant_id = await self._create_tenant(conn)
            wf_id = uuid.uuid4()
            steps = json.dumps([{"id": "step1", "type": "http"}])
            trigger_config = json.dumps({"cron": "*/5 * * * *"})
            await conn.execute(
                "INSERT INTO workflows "
                "(id, tenant_id, name, description, trigger_type, trigger_config, "
                "steps, is_active, webhook_path, webhook_secret) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10)",
                wf_id,
                tenant_id,
                "Full Workflow",
                "A test workflow",
                "cron",
                trigger_config,
                steps,
                True,
                f"/hooks/{wf_id.hex[:8]}",
                "secret123",
            )
            row = await conn.fetchrow("SELECT * FROM workflows WHERE id = $1", wf_id)
        assert row["name"] == "Full Workflow"
        assert row["description"] == "A test workflow"
        assert row["trigger_type"] == "cron"
        assert row["is_active"] is True
        assert row["webhook_secret"] == "secret123"
