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

if [ "$PULL_CHANGES" = "1" ]; then
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
