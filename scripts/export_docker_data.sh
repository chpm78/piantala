#!/bin/sh

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
EXPORT_DIR="${EXPORT_DIR:-$PROJECT_DIR/exports}"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

mkdir -p "$EXPORT_DIR"

INSTANCE_EXPORT="$EXPORT_DIR/piantala-instance-$TIMESTAMP.tgz"
UPLOADS_EXPORT="$EXPORT_DIR/piantala-uploads-$TIMESTAMP.tgz"

echo "Project directory: $PROJECT_DIR"
echo "Export directory:  $EXPORT_DIR"

echo "Exporting database volume to $INSTANCE_EXPORT"
docker run --rm \
  -v piantala_instance:/source \
  -v "$EXPORT_DIR":/export \
  alpine \
  tar czf "/export/$(basename "$INSTANCE_EXPORT")" -C /source .

echo "Exporting uploads volume to $UPLOADS_EXPORT"
docker run --rm \
  -v piantala_uploads:/source \
  -v "$EXPORT_DIR":/export \
  alpine \
  tar czf "/export/$(basename "$UPLOADS_EXPORT")" -C /source .

echo
echo "Export complete:"
echo "  $INSTANCE_EXPORT"
echo "  $UPLOADS_EXPORT"
