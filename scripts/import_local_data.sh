#!/bin/sh

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
INSTANCE_DIR="$PROJECT_DIR/instance"
UPLOADS_DIR="$PROJECT_DIR/piantala/static/uploads"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

INSTANCE_ARCHIVE="${1:-}"
UPLOADS_ARCHIVE="${2:-}"

if [ -z "$INSTANCE_ARCHIVE" ]; then
  echo "Usage: $0 /path/to/piantala-instance-YYYYMMDD-HHMMSS.tgz [/path/to/piantala-uploads-YYYYMMDD-HHMMSS.tgz]" >&2
  exit 1
fi

if [ ! -f "$INSTANCE_ARCHIVE" ]; then
  echo "Error: instance archive not found: $INSTANCE_ARCHIVE" >&2
  exit 1
fi

if [ -n "$UPLOADS_ARCHIVE" ] && [ ! -f "$UPLOADS_ARCHIVE" ]; then
  echo "Error: uploads archive not found: $UPLOADS_ARCHIVE" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR" "$INSTANCE_DIR" "$UPLOADS_DIR"

if [ -f "$INSTANCE_DIR/piantala.db" ]; then
  cp "$INSTANCE_DIR/piantala.db" "$BACKUP_DIR/piantala-local-instance-before-import-$TIMESTAMP.db"
fi

if [ -n "$UPLOADS_ARCHIVE" ] && [ -d "$UPLOADS_DIR" ]; then
  tar czf "$BACKUP_DIR/piantala-local-uploads-before-import-$TIMESTAMP.tgz" -C "$UPLOADS_DIR" .
fi

echo "Importing database from $INSTANCE_ARCHIVE"
rm -f "$INSTANCE_DIR/piantala.db"
tar xzf "$INSTANCE_ARCHIVE" -C "$INSTANCE_DIR"

if [ -n "$UPLOADS_ARCHIVE" ]; then
  echo "Importing uploads from $UPLOADS_ARCHIVE"
  find "$UPLOADS_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  tar xzf "$UPLOADS_ARCHIVE" -C "$UPLOADS_DIR"
fi

echo
echo "Import complete."
echo "Local backups saved in: $BACKUP_DIR"
