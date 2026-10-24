#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

trap 'echo "ERROR: Setup failed near line ${LINENO}." >&2' ERR

MODE="check-only"

case "${1:-}" in
    "")
        ;;
    --check-only)
        MODE="check-only"
        ;;
    --apply)
        MODE="apply"
        ;;
    --help|-h)
        echo "Usage: bash deploy/setup.sh [--check-only|--apply]"
        echo
        echo "  --check-only  Validate configuration only (default)."
        echo "  --apply       Build images and start application services."
        exit 0
        ;;
    *)
        echo "ERROR: Unknown argument: $1" >&2
        exit 1
        ;;
esac

for command_name in docker env grep sed awk tail cut tr; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "ERROR: Required command not found: $command_name" >&2
        exit 1
    fi
done

if [[ ! -f ".env" ]]; then
    echo "ERROR: .env was not found in the project root." >&2
    exit 1
fi

if [[ ! -f "docker-compose.yml" ]]; then
    echo "ERROR: docker-compose.yml was not found." >&2
    exit 1
fi

# Use .env as the source of truth for Compose interpolation.
# Inherited process variables must not silently override its values.
compose() {
    env \
        -u DB_NAME \
        -u DB_USER \
        -u DB_PASSWORD \
        -u LLM_PROVIDER \
        -u LLM_BASE_URL \
        -u LLM_MODEL \
        -u LLM_API_KEY \
        docker compose "$@"
}

if ! compose version >/dev/null 2>&1; then
    echo "ERROR: Docker Compose v2 is required." >&2
    exit 1
fi

# Read a setting without sourcing or executing .env as shell code.
read_env_value() {
    local key="$1"
    local line
    local value

    line="$(
        grep -E "^[[:space:]]*${key}[[:space:]]*=" .env |
            tail -n 1 || true
    )"

    if [[ -z "$line" ]]; then
        printf ''
        return 0
    fi

    value="${line#*=}"

    value="$(
        printf '%s' "$value" |
            sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
    )"

    # Remove matching outer quotes.
    if [[ "$value" =~ ^\".*\"$ ]]; then
        value="${value:1:${#value}-2}"
    elif [[ "$value" =~ ^\'.*\'$ ]]; then
        value="${value:1:${#value}-2}"
    else
        # Remove an unquoted inline comment.
        value="${value%%#*}"
        value="$(
            printf '%s' "$value" |
                sed -E 's/[[:space:]]+$//'
        )"
    fi

    printf '%s' "$value" | tr -d '\r'
}

LLM_PROVIDER="$(read_env_value LLM_PROVIDER)"
LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
LLM_PROVIDER="$(printf '%s' "$LLM_PROVIDER" | tr '[:upper:]' '[:lower:]')"

LLM_BASE_URL="$(read_env_value LLM_BASE_URL)"
LLM_MODEL="$(read_env_value LLM_MODEL)"

if [[ -z "$LLM_BASE_URL" ]]; then
    if [[ "$LLM_PROVIDER" == "ollama" ]]; then
        LLM_BASE_URL="http://ollama:11434/api"
    else
        LLM_BASE_URL="http://localhost:8000/v1"
    fi
fi

if [[ -z "$LLM_MODEL" ]]; then
    LLM_MODEL="qwen2.5:3b"
fi

case "$LLM_PROVIDER" in
    ollama)
        COMPOSE_PROFILE=(--profile ollama)
        echo "LLM provider: Ollama"
        ;;
    openai_compatible)
        COMPOSE_PROFILE=()
        echo "LLM provider: OpenAI-compatible API"
        ;;
    *)
        echo "ERROR: Unsupported LLM_PROVIDER: $LLM_PROVIDER" >&2
        echo "Use ollama or openai_compatible in .env." >&2
        exit 1
        ;;
esac

if [[ "$LLM_BASE_URL" != http://* && "$LLM_BASE_URL" != https://* ]]; then
    echo "ERROR: LLM_BASE_URL must start with http:// or https://." >&2
    exit 1
fi

if [[ "$LLM_BASE_URL" == "http://" || "$LLM_BASE_URL" == "https://" ]]; then
    echo "ERROR: LLM_BASE_URL is incomplete." >&2
    exit 1
fi

if [[ -z "$LLM_MODEL" ]]; then
    echo "ERROR: LLM_MODEL must not be empty." >&2
    exit 1
fi

# Validate required database settings without displaying their values.
for setting_name in DB_NAME DB_USER DB_PASSWORD; do
    if [[ -z "$(read_env_value "$setting_name")" ]]; then
        echo "ERROR: Set a non-empty ${setting_name} in .env." >&2
        exit 1
    fi
done

echo
echo "Validating Docker Compose configuration..."

compose "${COMPOSE_PROFILE[@]}" config --quiet

echo "SUCCESS: Docker Compose configuration is valid."

if [[ "$MODE" == "check-only" ]]; then
    echo
    echo "Check-only mode: no images will be built."
    echo "No services will be started and no models will be downloaded."
    echo "After reviewing the configuration on the deployment server, run:"
    echo "bash deploy/setup.sh --apply"
    exit 0
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker Engine is not available." >&2
    echo "Start Docker Engine and try again." >&2
    exit 1
fi

if [[ "$LLM_PROVIDER" == "ollama" ]]; then
    echo
    echo "WARNING: Ollama may consume substantial RAM and disk space."
    echo "Check available resources before proceeding."
    read -r -p 'Type INSTALL to continue: ' confirmation

    if [[ "$confirmation" != "INSTALL" ]]; then
        echo "Deployment cancelled."
        exit 0
    fi
fi

echo
echo "Building Django and AI service images..."

compose build django ai_service

echo
echo "Starting PostgreSQL and Redis..."

compose up -d postgres redis

if [[ "$LLM_PROVIDER" == "ollama" ]]; then
    echo
    echo "Starting Ollama..."

    compose --profile ollama up -d ollama

    echo
    echo "Preparing the configured Ollama model..."

    compose --profile ollama run --rm ollama-model-init
fi

echo
echo "Starting AI service and Django..."

compose "${COMPOSE_PROFILE[@]}" up -d ai_service django

echo
echo "======================================"
echo " Deployment commands completed"
echo "======================================"

echo
echo "Current service status:"
compose "${COMPOSE_PROFILE[@]}" ps

echo
echo "Inspect health and logs before using the application:"
echo "docker compose logs --tail=100 ai_service django"