#!/bin/sh

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
PULL_CHANGES="${PULL_CHANGES:-1}"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "Error: neither 'docker compose' nor 'docker-compose' is available." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "Project directory: $PROJECT_DIR"
echo "Backup directory:  $BACKUP_DIR"
echo "Compose command:   $COMPOSE_CMD"

cd "$PROJECT_DIR"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # Ignore executable-bit drift on deployment hosts so helper scripts do not block pulls.
  git config core.fileMode false
fi

if [ "$PULL_CHANGES" = "1" ]; then
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Error: local tracked changes are present. Commit, stash, or restore them before updating." >&2
    git status --short >&2
    exit 1
  fi
  echo "Pulling latest git changes..."
  git pull --ff-only
fi

INSTANCE_BACKUP="$BACKUP_DIR/piantala-instance-$TIMESTAMP.tgz"
UPLOADS_BACKUP="$BACKUP_DIR/piantala-uploads-$TIMESTAMP.tgz"

echo "Creating database backup: $INSTANCE_BACKUP"
docker run --rm \
  -v piantala_instance:/source \
  -v "$BACKUP_DIR":/backup \
  alpine \
  tar czf "/backup/$(basename "$INSTANCE_BACKUP")" -C /source .

echo "Creating uploads backup: $UPLOADS_BACKUP"
docker run --rm \
  -v piantala_uploads:/source \
  -v "$BACKUP_DIR":/backup \
  alpine \
  tar czf "/backup/$(basename "$UPLOADS_BACKUP")" -C /source .

echo "Rebuilding and restarting Piantala..."
$COMPOSE_CMD up -d --build

echo "Current container status:"
$COMPOSE_CMD ps

echo
echo "Update complete."
echo "Backups created:"
echo "  $INSTANCE_BACKUP"
echo "  $UPLOADS_BACKUP"
