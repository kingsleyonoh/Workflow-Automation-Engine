#!/usr/bin/env bash
# Deploy the Workflow Automation Engine to a VPS with Docker + Traefik.
#
# Usage:
#   Run on the VPS directly:
#     ./scripts/deploy.sh
#
#   Run remotely via SSH:
#     ssh user@your-vps "cd /opt/workflow-engine && ./scripts/deploy.sh"
#
# Prerequisites:
#   - Docker and Docker Compose installed on the VPS
#   - Traefik running as a reverse proxy with the 'traefik-public' network
#   - .env file configured with production values (see .env.production.example)
#   - Git repository cloned to the deployment directory

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="docker-compose.prod.yml"
LOG_PREFIX="[deploy]"

log() {
    echo "${LOG_PREFIX} $(date '+%Y-%m-%d %H:%M:%S') $*"
}

error() {
    echo "${LOG_PREFIX} ERROR: $*" >&2
    exit 1
}

# Verify prerequisites
check_prerequisites() {
    log "Checking prerequisites..."

    if ! command -v docker &>/dev/null; then
        error "Docker is not installed"
    fi

    if ! docker compose version &>/dev/null; then
        error "Docker Compose is not available"
    fi

    if [ ! -f "${DEPLOY_DIR}/${COMPOSE_FILE}" ]; then
        error "Compose file not found: ${DEPLOY_DIR}/${COMPOSE_FILE}"
    fi

    if [ ! -f "${DEPLOY_DIR}/.env" ]; then
        error ".env file not found. Copy .env.production.example to .env and configure it."
    fi

    # Check Traefik network exists
    if ! docker network inspect traefik-public &>/dev/null; then
        log "Creating traefik-public network..."
        docker network create traefik-public
    fi

    log "Prerequisites OK"
}

# Pull latest code
pull_latest() {
    log "Pulling latest code..."
    cd "${DEPLOY_DIR}"

    git fetch origin
    git pull origin main

    log "Code updated to: $(git rev-parse --short HEAD)"
}

# Build and deploy containers
deploy_containers() {
    log "Building and deploying containers..."
    cd "${DEPLOY_DIR}"

    # Build images
    docker compose -f "${COMPOSE_FILE}" build --no-cache

    # Stop existing containers
    docker compose -f "${COMPOSE_FILE}" down --timeout 30

    # Start services (postgres and redis first, then app and worker)
    docker compose -f "${COMPOSE_FILE}" up -d

    log "Containers started"
}

# Run database migrations
run_migrations() {
    log "Running database migrations..."
    cd "${DEPLOY_DIR}"

    # Wait for postgres to be healthy
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker compose -f "${COMPOSE_FILE}" exec -T postgres pg_isready -U postgres &>/dev/null; then
            break
        fi
        log "Waiting for PostgreSQL to be ready... (${retries} retries left)"
        sleep 2
        retries=$((retries - 1))
    done

    if [ $retries -eq 0 ]; then
        error "PostgreSQL did not become ready in time"
    fi

    # Run Alembic migrations inside the app container
    docker compose -f "${COMPOSE_FILE}" exec -T app python -m alembic upgrade head

    log "Migrations complete"
}

# Verify deployment
verify_deployment() {
    log "Verifying deployment..."
    cd "${DEPLOY_DIR}"

    # Wait for the app to be healthy
    local retries=20
    while [ $retries -gt 0 ]; do
        if docker compose -f "${COMPOSE_FILE}" exec -T app wget -q --spider http://localhost:8000/api/health 2>/dev/null; then
            break
        fi
        log "Waiting for app health check... (${retries} retries left)"
        sleep 3
        retries=$((retries - 1))
    done

    if [ $retries -eq 0 ]; then
        log "WARNING: Health check did not pass. Check container logs:"
        docker compose -f "${COMPOSE_FILE}" logs --tail=20 app
        error "Deployment verification failed"
    fi

    log "Health check passed"

    # Show running containers
    docker compose -f "${COMPOSE_FILE}" ps

    log "Deployment complete!"
    log "App: https://workflows.kingsleyonoh.com"
    log "Health: https://workflows.kingsleyonoh.com/api/health"
}

# Main deployment flow
main() {
    log "Starting deployment..."
    log "Deploy directory: ${DEPLOY_DIR}"

    check_prerequisites
    pull_latest
    deploy_containers
    run_migrations
    verify_deployment

    log "Deployment finished successfully"
}

main "$@"
