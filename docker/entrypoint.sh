#!/bin/sh
set -eu

mkdir -p /app/instance /app/piantala/static/uploads

python /app/docker/bootstrap_admin.py

exec "$@"
