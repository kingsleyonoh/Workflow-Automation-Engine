"""Integration tests for Alembic migrations — executions and step_executions tables.

Tests verify that tables exist, columns have correct types,
constraints are enforced, indexes exist, and FK relationships work.
Runs against the real local PostgreSQL test database.
"""

import json
import uuid
from datetime import datetime

import asyncpg
import pytest

pytestmark = pytest.mark.integration


async def _create_tenant(conn) -> uuid.UUID:
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


# ─── Executions Table Tests ────────────────────────────────────────


class TestExecutionsTable:
    """Tests for the executions table schema and constraints."""

    async def test_executions_table_exists(self, migrated_db):
        """Executions table is created by migration."""
        async with migrated_db.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'executions')"
            )
        assert exists is True

    async def test_executions_columns_exist(self, migrated_db):
        """All required columns exist."""
        async with migrated_db.acquire() as conn:
            columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'executions'"
            )
        col_names = {r["column_name"] for r in columns}
        expected = {
            "id",
            "tenant_id",
            "workflow_id",
            "status",
            "trigger_data",
            "context",
            "replayed_from",
            "started_at",
            "completed_at",
            "error",
            "duration_ms",
            "created_at",
        }
        assert expected.issubset(col_names)

    async def test_executions_id_is_uuid(self, migrated_db):
        """id column is UUID type."""
        async with migrated_db.acquire() as conn:
            col = await conn.fetchrow(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'executions' AND column_name = 'id'"
            )
        assert col["data_type"] == "uuid"

    async def test_executions_tenant_id_fk(self, migrated_db):
        """tenant_id FK references tenants.id."""
        async with migrated_db.acquire() as conn:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO executions (id, tenant_id, workflow_id) "
                    "VALUES ($1, $2, $3)",
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                )

    async def test_executions_workflow_id_fk(self, migrated_db):
        """workflow_id FK references workflows.id."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO executions (id, tenant_id, workflow_id) "
                    "VALUES ($1, $2, $3)",
                    uuid.uuid4(),
                    tenant_id,
                    uuid.uuid4(),
                )

    async def test_executions_status_defaults_pending(self, migrated_db):
        """status defaults to 'pending'."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO executions (id, tenant_id, workflow_id) "
                "VALUES ($1, $2, $3)",
                exec_id,
                tenant_id,
                wf_id,
            )
            result = await conn.fetchval(
                "SELECT status FROM executions WHERE id = $1", exec_id
            )
        assert result == "pending"

    async def test_executions_trigger_data_defaults_empty_json(self, migrated_db):
        """trigger_data defaults to empty JSON object."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO executions (id, tenant_id, workflow_id) "
                "VALUES ($1, $2, $3)",
                exec_id,
                tenant_id,
                wf_id,
            )
            result = await conn.fetchval(
                "SELECT trigger_data::text FROM executions WHERE id = $1", exec_id
            )
        assert json.loads(result) == {}

    async def test_executions_context_defaults_empty_json(self, migrated_db):
        """context defaults to empty JSON object."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO executions (id, tenant_id, workflow_id) "
                "VALUES ($1, $2, $3)",
                exec_id,
                tenant_id,
                wf_id,
            )
            result = await conn.fetchval(
                "SELECT context::text FROM executions WHERE id = $1", exec_id
            )
        assert json.loads(result) == {}

    async def test_executions_replayed_from_nullable(self, migrated_db):
        """replayed_from is nullable (self FK)."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO executions (id, tenant_id, workflow_id, replayed_from) "
                "VALUES ($1, $2, $3, $4)",
                exec_id,
                tenant_id,
                wf_id,
                None,
            )
            result = await conn.fetchval(
                "SELECT replayed_from FROM executions WHERE id = $1", exec_id
            )
        assert result is None

    async def test_executions_replayed_from_self_fk(self, migrated_db):
        """replayed_from FK references executions.id."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            # Create original execution
            orig_id = await _create_execution(conn, tenant_id, wf_id)
            # Create replay execution referencing original
            replay_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO executions (id, tenant_id, workflow_id, replayed_from) "
                "VALUES ($1, $2, $3, $4)",
                replay_id,
                tenant_id,
                wf_id,
                orig_id,
            )
            result = await conn.fetchval(
                "SELECT replayed_from FROM executions WHERE id = $1", replay_id
            )
        assert result == orig_id

    async def test_executions_started_at_nullable(self, migrated_db):
        """started_at is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            result = await conn.fetchval(
                "SELECT started_at FROM executions WHERE id = $1", exec_id
            )
        assert result is None

    async def test_executions_error_nullable(self, migrated_db):
        """error column is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            result = await conn.fetchval(
                "SELECT error FROM executions WHERE id = $1", exec_id
            )
        assert result is None

    async def test_executions_duration_ms_nullable(self, migrated_db):
        """duration_ms is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            result = await conn.fetchval(
                "SELECT duration_ms FROM executions WHERE id = $1", exec_id
            )
        assert result is None

    async def test_executions_created_at_default(self, migrated_db):
        """created_at defaults to current timestamp."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            result = await conn.fetchval(
                "SELECT created_at FROM executions WHERE id = $1", exec_id
            )
        assert isinstance(result, datetime)

    async def test_executions_cascade_on_workflow_delete(self, migrated_db):
        """Deleting a workflow cascades to delete its executions."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            await conn.execute("DELETE FROM workflows WHERE id = $1", wf_id)
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM executions WHERE id = $1", exec_id
            )
        assert count == 0

    async def test_executions_index_tenant_workflow_status(self, migrated_db):
        """Composite INDEX exists on (tenant_id, workflow_id, status)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'executions'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "workflow_id" in defn and "status" in defn
            for defn in index_defs.values()
        )

    async def test_executions_index_tenant_status_created(self, migrated_db):
        """Composite INDEX exists on (tenant_id, status, created_at)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'executions'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "status" in defn and "created_at" in defn
            for defn in index_defs.values()
        )

    async def test_executions_happy_path(self, migrated_db):
        """Full execution insert with all fields succeeds."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO executions "
                "(id, tenant_id, workflow_id, status, trigger_data, context, "
                "error, duration_ms) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)",
                exec_id,
                tenant_id,
                wf_id,
                "completed",
                json.dumps({"source": "webhook"}),
                json.dumps({"step1": {"result": "ok"}}),
                None,
                1500,
            )
            row = await conn.fetchrow(
                "SELECT * FROM executions WHERE id = $1", exec_id
            )
        assert row["status"] == "completed"
        assert row["duration_ms"] == 1500


# ─── Step Executions Table Tests ───────────────────────────────────


class TestStepExecutionsTable:
    """Tests for the step_executions table schema and constraints."""

    async def test_step_executions_table_exists(self, migrated_db):
        """Step executions table is created by migration."""
        async with migrated_db.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'step_executions')"
            )
        assert exists is True

    async def test_step_executions_columns_exist(self, migrated_db):
        """All required columns exist."""
        async with migrated_db.acquire() as conn:
            columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'step_executions'"
            )
        col_names = {r["column_name"] for r in columns}
        expected = {
            "id",
            "tenant_id",
            "execution_id",
            "step_id",
            "step_type",
            "status",
            "input_data",
            "output_data",
            "error",
            "attempt",
            "max_attempts",
            "started_at",
            "completed_at",
            "duration_ms",
            "created_at",
        }
        assert expected.issubset(col_names)

    async def test_step_executions_tenant_id_fk(self, migrated_db):
        """tenant_id FK references tenants.id."""
        async with migrated_db.acquire() as conn:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO step_executions "
                    "(id, tenant_id, execution_id, step_id, step_type) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                    "step_1",
                    "http",
                )

    async def test_step_executions_execution_id_fk(self, migrated_db):
        """execution_id FK references executions.id."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO step_executions "
                    "(id, tenant_id, execution_id, step_id, step_type) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    uuid.uuid4(),
                    "step_1",
                    "http",
                )

    async def test_step_executions_step_id_not_null(self, migrated_db):
        """step_id column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO step_executions "
                    "(id, tenant_id, execution_id, step_id, step_type) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    exec_id,
                    None,
                    "http",
                )

    async def test_step_executions_step_type_not_null(self, migrated_db):
        """step_type column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO step_executions "
                    "(id, tenant_id, execution_id, step_id, step_type) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    exec_id,
                    "step_1",
                    None,
                )

    async def test_step_executions_status_defaults_pending(self, migrated_db):
        """status defaults to 'pending'."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type) "
                "VALUES ($1, $2, $3, $4, $5)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
            )
            result = await conn.fetchval(
                "SELECT status FROM step_executions WHERE id = $1", se_id
            )
        assert result == "pending"

    async def test_step_executions_input_data_defaults_empty_json(self, migrated_db):
        """input_data defaults to empty JSON object."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type) "
                "VALUES ($1, $2, $3, $4, $5)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
            )
            result = await conn.fetchval(
                "SELECT input_data::text FROM step_executions WHERE id = $1", se_id
            )
        assert json.loads(result) == {}

    async def test_step_executions_output_data_nullable(self, migrated_db):
        """output_data is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type) "
                "VALUES ($1, $2, $3, $4, $5)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
            )
            result = await conn.fetchval(
                "SELECT output_data FROM step_executions WHERE id = $1", se_id
            )
        assert result is None

    async def test_step_executions_attempt_defaults_1(self, migrated_db):
        """attempt defaults to 1."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type) "
                "VALUES ($1, $2, $3, $4, $5)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
            )
            result = await conn.fetchval(
                "SELECT attempt FROM step_executions WHERE id = $1", se_id
            )
        assert result == 1

    async def test_step_executions_max_attempts_defaults_3(self, migrated_db):
        """max_attempts defaults to 3."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type) "
                "VALUES ($1, $2, $3, $4, $5)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
            )
            result = await conn.fetchval(
                "SELECT max_attempts FROM step_executions WHERE id = $1", se_id
            )
        assert result == 3

    async def test_step_executions_cascade_on_execution_delete(self, migrated_db):
        """Deleting an execution cascades to delete its step_executions."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type) "
                "VALUES ($1, $2, $3, $4, $5)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
            )
            await conn.execute("DELETE FROM executions WHERE id = $1", exec_id)
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM step_executions WHERE id = $1", se_id
            )
        assert count == 0

    async def test_step_executions_created_at_default(self, migrated_db):
        """created_at defaults to current timestamp."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type) "
                "VALUES ($1, $2, $3, $4, $5)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
            )
            result = await conn.fetchval(
                "SELECT created_at FROM step_executions WHERE id = $1", se_id
            )
        assert isinstance(result, datetime)

    async def test_step_executions_index_tenant_execution_step(self, migrated_db):
        """Composite INDEX exists on (tenant_id, execution_id, step_id)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'step_executions'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "execution_id" in defn and "step_id" in defn
            for defn in index_defs.values()
        )

    async def test_step_executions_index_tenant_status(self, migrated_db):
        """Composite INDEX exists on (tenant_id, status)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'step_executions'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "status" in defn
            for defn in index_defs.values()
        )

    async def test_step_executions_happy_path(self, migrated_db):
        """Full step_execution insert with all fields succeeds."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            se_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO step_executions "
                "(id, tenant_id, execution_id, step_id, step_type, status, "
                "input_data, output_data, error, attempt, max_attempts, "
                "duration_ms) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, "
                "$9, $10, $11, $12)",
                se_id,
                tenant_id,
                exec_id,
                "step_1",
                "http",
                "completed",
                json.dumps({"url": "https://api.example.com"}),
                json.dumps({"status_code": 200}),
                None,
                1,
                3,
                250,
            )
            row = await conn.fetchrow(
                "SELECT * FROM step_executions WHERE id = $1", se_id
            )
        assert row["step_type"] == "http"
        assert row["status"] == "completed"
        assert row["duration_ms"] == 250
