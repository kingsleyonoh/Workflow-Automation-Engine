"""Integration tests for Alembic migrations — execution_logs and webhook_deliveries.

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


# ─── Execution Logs Table Tests ────────────────────────────────────


class TestExecutionLogsTable:
    """Tests for the execution_logs table schema and constraints."""

    async def test_execution_logs_table_exists(self, migrated_db):
        """Execution logs table is created by migration."""
        async with migrated_db.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'execution_logs')"
            )
        assert exists is True

    async def test_execution_logs_columns_exist(self, migrated_db):
        """All required columns exist."""
        async with migrated_db.acquire() as conn:
            columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'execution_logs'"
            )
        col_names = {r["column_name"] for r in columns}
        expected = {
            "id",
            "tenant_id",
            "execution_id",
            "step_id",
            "level",
            "message",
            "data",
            "created_at",
        }
        assert expected.issubset(col_names)

    async def test_execution_logs_tenant_id_fk(self, migrated_db):
        """tenant_id FK references tenants.id."""
        async with migrated_db.acquire() as conn:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO execution_logs "
                    "(id, tenant_id, execution_id, level, message) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                    "info",
                    "test message",
                )

    async def test_execution_logs_execution_id_fk(self, migrated_db):
        """execution_id FK references executions.id."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO execution_logs "
                    "(id, tenant_id, execution_id, level, message) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    uuid.uuid4(),
                    "info",
                    "test message",
                )

    async def test_execution_logs_step_id_nullable(self, migrated_db):
        """step_id is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            log_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO execution_logs "
                "(id, tenant_id, execution_id, step_id, level, message) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                log_id,
                tenant_id,
                exec_id,
                None,
                "info",
                "Execution started",
            )
            result = await conn.fetchval(
                "SELECT step_id FROM execution_logs WHERE id = $1", log_id
            )
        assert result is None

    async def test_execution_logs_level_not_null(self, migrated_db):
        """level column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO execution_logs "
                    "(id, tenant_id, execution_id, level, message) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    exec_id,
                    None,
                    "test",
                )

    async def test_execution_logs_message_not_null(self, migrated_db):
        """message column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO execution_logs "
                    "(id, tenant_id, execution_id, level, message) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.uuid4(),
                    tenant_id,
                    exec_id,
                    "info",
                    None,
                )

    async def test_execution_logs_data_defaults_empty_json(self, migrated_db):
        """data defaults to empty JSON object."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            log_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO execution_logs "
                "(id, tenant_id, execution_id, level, message) "
                "VALUES ($1, $2, $3, $4, $5)",
                log_id,
                tenant_id,
                exec_id,
                "info",
                "test",
            )
            result = await conn.fetchval(
                "SELECT data::text FROM execution_logs WHERE id = $1", log_id
            )
        assert json.loads(result) == {}

    async def test_execution_logs_created_at_default(self, migrated_db):
        """created_at defaults to current timestamp."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            log_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO execution_logs "
                "(id, tenant_id, execution_id, level, message) "
                "VALUES ($1, $2, $3, $4, $5)",
                log_id,
                tenant_id,
                exec_id,
                "info",
                "test",
            )
            result = await conn.fetchval(
                "SELECT created_at FROM execution_logs WHERE id = $1", log_id
            )
        assert isinstance(result, datetime)

    async def test_execution_logs_cascade_on_execution_delete(self, migrated_db):
        """Deleting an execution cascades to delete its logs."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            log_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO execution_logs "
                "(id, tenant_id, execution_id, level, message) "
                "VALUES ($1, $2, $3, $4, $5)",
                log_id,
                tenant_id,
                exec_id,
                "info",
                "test",
            )
            await conn.execute("DELETE FROM executions WHERE id = $1", exec_id)
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM execution_logs WHERE id = $1", log_id
            )
        assert count == 0

    async def test_execution_logs_index_tenant_execution_created(self, migrated_db):
        """Composite INDEX exists on (tenant_id, execution_id, created_at)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'execution_logs'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "execution_id" in defn and "created_at" in defn
            for defn in index_defs.values()
        )

    async def test_execution_logs_happy_path(self, migrated_db):
        """Full execution log insert with all fields succeeds."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            log_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO execution_logs "
                "(id, tenant_id, execution_id, step_id, level, message, data) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)",
                log_id,
                tenant_id,
                exec_id,
                "step_1",
                "error",
                "HTTP request failed",
                json.dumps({"status_code": 500, "body": "Internal Server Error"}),
            )
            row = await conn.fetchrow(
                "SELECT * FROM execution_logs WHERE id = $1", log_id
            )
        assert row["level"] == "error"
        assert row["step_id"] == "step_1"
        assert row["message"] == "HTTP request failed"


# ─── Webhook Deliveries Table Tests ────────────────────────────────


class TestWebhookDeliveriesTable:
    """Tests for the webhook_deliveries table schema and constraints."""

    async def test_webhook_deliveries_table_exists(self, migrated_db):
        """Webhook deliveries table is created by migration."""
        async with migrated_db.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'webhook_deliveries')"
            )
        assert exists is True

    async def test_webhook_deliveries_columns_exist(self, migrated_db):
        """All required columns exist."""
        async with migrated_db.acquire() as conn:
            columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'webhook_deliveries'"
            )
        col_names = {r["column_name"] for r in columns}
        expected = {
            "id",
            "tenant_id",
            "workflow_id",
            "execution_id",
            "method",
            "headers",
            "payload",
            "source_ip",
            "status",
            "rejection_reason",
            "created_at",
        }
        assert expected.issubset(col_names)

    async def test_webhook_deliveries_tenant_id_fk(self, migrated_db):
        """tenant_id FK references tenants.id."""
        async with migrated_db.acquire() as conn:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO webhook_deliveries "
                    "(id, tenant_id, workflow_id, method) "
                    "VALUES ($1, $2, $3, $4)",
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                    "POST",
                )

    async def test_webhook_deliveries_workflow_id_fk(self, migrated_db):
        """workflow_id FK references workflows.id."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "INSERT INTO webhook_deliveries "
                    "(id, tenant_id, workflow_id, method) "
                    "VALUES ($1, $2, $3, $4)",
                    uuid.uuid4(),
                    tenant_id,
                    uuid.uuid4(),
                    "POST",
                )

    async def test_webhook_deliveries_execution_id_nullable(self, migrated_db):
        """execution_id is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, execution_id, method) "
                "VALUES ($1, $2, $3, $4, $5)",
                wd_id,
                tenant_id,
                wf_id,
                None,
                "POST",
            )
            result = await conn.fetchval(
                "SELECT execution_id FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert result is None

    async def test_webhook_deliveries_method_not_null(self, migrated_db):
        """method column rejects NULL values."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "INSERT INTO webhook_deliveries "
                    "(id, tenant_id, workflow_id, method) "
                    "VALUES ($1, $2, $3, $4)",
                    uuid.uuid4(),
                    tenant_id,
                    wf_id,
                    None,
                )

    async def test_webhook_deliveries_headers_defaults_empty_json(self, migrated_db):
        """headers defaults to empty JSON object."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, method) "
                "VALUES ($1, $2, $3, $4)",
                wd_id,
                tenant_id,
                wf_id,
                "POST",
            )
            result = await conn.fetchval(
                "SELECT headers::text FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert json.loads(result) == {}

    async def test_webhook_deliveries_payload_defaults_empty_json(self, migrated_db):
        """payload defaults to empty JSON object."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, method) "
                "VALUES ($1, $2, $3, $4)",
                wd_id,
                tenant_id,
                wf_id,
                "POST",
            )
            result = await conn.fetchval(
                "SELECT payload::text FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert json.loads(result) == {}

    async def test_webhook_deliveries_status_defaults_received(self, migrated_db):
        """status defaults to 'received'."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, method) "
                "VALUES ($1, $2, $3, $4)",
                wd_id,
                tenant_id,
                wf_id,
                "POST",
            )
            result = await conn.fetchval(
                "SELECT status FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert result == "received"

    async def test_webhook_deliveries_source_ip_nullable(self, migrated_db):
        """source_ip is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, method) "
                "VALUES ($1, $2, $3, $4)",
                wd_id,
                tenant_id,
                wf_id,
                "POST",
            )
            result = await conn.fetchval(
                "SELECT source_ip FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert result is None

    async def test_webhook_deliveries_rejection_reason_nullable(self, migrated_db):
        """rejection_reason is nullable."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, method) "
                "VALUES ($1, $2, $3, $4)",
                wd_id,
                tenant_id,
                wf_id,
                "POST",
            )
            result = await conn.fetchval(
                "SELECT rejection_reason FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert result is None

    async def test_webhook_deliveries_created_at_default(self, migrated_db):
        """created_at defaults to current timestamp."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, method) "
                "VALUES ($1, $2, $3, $4)",
                wd_id,
                tenant_id,
                wf_id,
                "POST",
            )
            result = await conn.fetchval(
                "SELECT created_at FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert isinstance(result, datetime)

    async def test_webhook_deliveries_cascade_on_workflow_delete(self, migrated_db):
        """Deleting a workflow cascades to delete its webhook deliveries."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, method) "
                "VALUES ($1, $2, $3, $4)",
                wd_id,
                tenant_id,
                wf_id,
                "POST",
            )
            await conn.execute("DELETE FROM workflows WHERE id = $1", wf_id)
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert count == 0

    async def test_webhook_deliveries_index_tenant_workflow_created(self, migrated_db):
        """Composite INDEX exists on (tenant_id, workflow_id, created_at)."""
        async with migrated_db.acquire() as conn:
            indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'webhook_deliveries'"
            )
        index_defs = {r["indexname"]: r["indexdef"] for r in indexes}
        assert any(
            "tenant_id" in defn and "workflow_id" in defn and "created_at" in defn
            for defn in index_defs.values()
        )

    async def test_webhook_deliveries_happy_path(self, migrated_db):
        """Full webhook delivery insert with all fields succeeds."""
        async with migrated_db.acquire() as conn:
            tenant_id = await _create_tenant(conn)
            wf_id = await _create_workflow(conn, tenant_id)
            exec_id = await _create_execution(conn, tenant_id, wf_id)
            wd_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO webhook_deliveries "
                "(id, tenant_id, workflow_id, execution_id, method, "
                "headers, payload, source_ip, status, rejection_reason) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10)",
                wd_id,
                tenant_id,
                wf_id,
                exec_id,
                "POST",
                json.dumps({"Content-Type": "application/json"}),
                json.dumps({"event": "push"}),
                "192.168.1.1",
                "accepted",
                None,
            )
            row = await conn.fetchrow(
                "SELECT * FROM webhook_deliveries WHERE id = $1", wd_id
            )
        assert row["method"] == "POST"
        assert row["status"] == "accepted"
        assert row["source_ip"] == "192.168.1.1"
