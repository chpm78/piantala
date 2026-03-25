#!/bin/sh

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
PULL_CHANGES="${PULL_CHANGES:-1}"
GIT_SYNC_MODE="${GIT_SYNC_MODE:-ff-only}"
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
echo "Git sync mode:     $GIT_SYNC_MODE"

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
  echo "Fetching latest git changes..."
  git fetch origin

  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  if [ "$CURRENT_BRANCH" = "HEAD" ]; then
    echo "Error: repository is in detached HEAD state. Check out the deployment branch before updating." >&2
    exit 1
  fi

  if ! git show-ref --verify --quiet "refs/remotes/origin/$CURRENT_BRANCH"; then
    echo "Error: remote branch origin/$CURRENT_BRANCH does not exist." >&2
    exit 1
  fi

  LOCAL_HEAD=$(git rev-parse HEAD)
  REMOTE_HEAD=$(git rev-parse "origin/$CURRENT_BRANCH")
  BASE_HEAD=$(git merge-base HEAD "origin/$CURRENT_BRANCH")

  if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    echo "Git is already up to date."
  elif [ "$LOCAL_HEAD" = "$BASE_HEAD" ]; then
    echo "Fast-forwarding to origin/$CURRENT_BRANCH..."
    git merge --ff-only "origin/$CURRENT_BRANCH"
  elif [ "$REMOTE_HEAD" = "$BASE_HEAD" ]; then
    echo "Error: local branch is ahead of origin/$CURRENT_BRANCH." >&2
    echo "The deployment host has local commits that are not on GitHub." >&2
    echo "Suggested recovery:" >&2
    echo "  git branch deployment-backup-$TIMESTAMP" >&2
    echo "  git reset --hard origin/$CURRENT_BRANCH" >&2
    exit 1
  else
    echo "Error: local branch and origin/$CURRENT_BRANCH have diverged." >&2
    echo "Suggested recovery options:" >&2
    echo "  Keep a backup branch, then reset to GitHub:" >&2
    echo "    git branch deployment-backup-$TIMESTAMP" >&2
    echo "    git reset --hard origin/$CURRENT_BRANCH" >&2
    echo "  Or inspect the divergence first:" >&2
    echo "    git log --oneline --decorate --graph --all -20" >&2
    if [ "$GIT_SYNC_MODE" = "reset" ]; then
      echo "GIT_SYNC_MODE=reset set, creating backup branch and resetting automatically..."
      git branch "deployment-backup-$TIMESTAMP"
      git reset --hard "origin/$CURRENT_BRANCH"
    else
      echo "Tip: rerun with GIT_SYNC_MODE=reset to let this script create a backup branch and reset automatically." >&2
      exit 1
    fi
  fi
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
