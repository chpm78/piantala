# Piantala

Piantala is a Flask web app for managing a garden with a visual map, optional Google Maps homepage, nested photo-driven areas, plant records, user roles, external links, and Home Assistant entity values.

## Current scope

- Local-first Flask app
- SQLite database for easy startup
- Multi-user authentication with role-based permissions
- Map homepage with clickable garden locations
- Optional Google Maps homepage for top-level locations
- Up to 4 content levels:
  - Level 1: map location / macro area
  - Level 2: area detail
  - Level 3: bed / subsection
  - Level 4: single plant
- Per-node:
  - hero image
  - photo gallery
  - external links
  - Home Assistant entity values
  - clickable hotspots to child nodes directly on the image

The layout is intentionally simple and file-based so we can add Docker support next without refactoring the app structure.

## Quick start

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install the app:

```bash
pip install -e .
```

3. Initialize the database and seed system roles:

```bash
flask --app app init-db
```

4. Create the first admin user:

```bash
flask --app app create-admin --username admin --email admin@example.com --password change-me
```

5. Run the development server:

```bash
flask --app app run --debug
```

Open `http://127.0.0.1:5000`.

## Docker deployment

Piantala now includes a Docker setup for running on a local or remote Docker host.

### What persists

The Docker stack keeps application data in two named volumes:

- `piantala-instance`: SQLite database and Flask instance data
- `piantala-uploads`: uploaded images

That means you can rebuild or replace the container without losing your database or uploaded photos.

### First deployment

1. Copy the project to the remote server:

```bash
git clone <your-repo-url> piantala
cd piantala
```

2. Create a `.env` file for Docker:

```bash
SECRET_KEY=replace-this-with-a-long-random-secret
PIANTALA_PORT=8000
DATABASE_URL=sqlite:////app/instance/piantala.db
UPLOAD_FOLDER=/app/piantala/static/uploads

# optional
GOOGLE_MAPS_API_KEY=

# bootstrap first admin user on first start
PIANTALA_ADMIN_USERNAME=admin
PIANTALA_ADMIN_EMAIL=admin@example.com
PIANTALA_ADMIN_PASSWORD=change-me-now
```

3. Build and start the stack:

```bash
docker compose up -d --build
```

4. Open the server at `http://your-server:8000`.

5. Check container health:

```bash
docker compose ps
docker compose logs -f
```

The container startup will:

- create the database schema if needed
- apply the current schema sync
- seed system roles
- create the first admin user if the three `PIANTALA_ADMIN_*` variables are set and that user does not already exist

After the first successful startup, it is a good idea to remove `PIANTALA_ADMIN_PASSWORD` from `.env` so the bootstrap secret is not kept around unnecessarily.

### Recommended remote setup

For a real remote installation, the usual next step is:

1. run Piantala on Docker at port `8000`
2. put Nginx, Caddy, or Traefik in front of it
3. terminate HTTPS at the reverse proxy
4. keep Piantala private to the local Docker network if possible

That gives you TLS, cleaner domain handling, and easier future updates.

### Updating the app

With the named volumes above, the safest normal update flow is:

```bash
cd piantala
git pull
docker compose build
docker compose up -d
```

Because the database and uploads live in Docker volumes, updates replace the app container but keep the data.

### Backups before updates

Before updating, back up both persistent volumes:

```bash
docker run --rm -v piantala_instance:/source -v "$(pwd)":/backup alpine tar czf /backup/piantala-instance-backup.tgz -C /source .
docker run --rm -v piantala_uploads:/source -v "$(pwd)":/backup alpine tar czf /backup/piantala-uploads-backup.tgz -C /source .
```

This is especially important while the project still uses SQLite.

### Rollback strategy

If an update goes wrong:

1. switch the code back to the previous git commit or tag
2. rebuild the image
3. restart with `docker compose up -d`
4. if needed, restore the saved volumes from backup

### Managing updates cleanly

For open-source/public development, a simple and reliable workflow is:

1. keep Piantala in git
2. tag stable releases, for example `v0.2.0`
3. deploy only tagged versions to the remote server
4. back up volumes before each deployment
5. pull the tag, rebuild, and restart

That gives you repeatable deployments and easy rollback points.

### SQLite now, Postgres later

SQLite is fine for the current single-container setup and is the easiest way to move your existing app to Docker.

Later, if you want stronger concurrency or more formal migration workflows, the next upgrade path is:

- add PostgreSQL as a second container
- move from the current schema-sync approach to Alembic migrations
- keep uploads in a mounted volume or move them to object storage

For now, the included Docker setup is a good fit for an early self-hosted Piantala instance.

### Health checks

The Docker stack now exposes an internal health endpoint at `/healthz` and the compose service uses it as a container healthcheck. That gives you a quick way to see whether the app is up after deploys:

```bash
docker compose ps
```

The service should eventually show as `healthy`.

## Map providers

Piantala currently supports:

- `Image map`: upload your own overview image and place level-1 nodes with X/Y coordinates
- `Google Maps`: requires an API key
- `OpenStreetMap`: no API key required
- `OpenTopoMap`: no API key required

If you want to use Google Maps for the homepage:

1. Create a Google Maps JavaScript API key.
2. Put it in `.env`:

```bash
GOOGLE_MAPS_API_KEY=your-key-here
```

3. In Piantala, open the map settings page and switch the homepage provider to `Google Maps`.

For `OpenStreetMap` and `OpenTopoMap`, no API key is required. These two providers are rendered with Leaflet.

Top-level locations can then be placed with latitude and longitude, while lower levels use clickable image hotspots.

For public deployment, do not assume the default OpenStreetMap tile server is appropriate for production traffic. For larger usage you should switch to a hosted tile service or self-host tiles.

## Roles and permissions

Seeded roles:

- `admin`: full access, including user management
- `editor`: manage garden content but not users
- `viewer`: read-only access

## Project structure

```text
piantala/
├── app.py
├── pyproject.toml
├── instance/
└── piantala/
    ├── __init__.py
    ├── admin.py
    ├── auth.py
    ├── config.py
    ├── extensions.py
    ├── forms.py
    ├── main.py
    ├── models.py
    ├── utils.py
    ├── static/
    └── templates/
```

## Open-source readiness

The app is packaged as a normal Python project and avoids environment-specific assumptions. That keeps the next steps straightforward:

- add tests
- add Home Assistant API sync
- add import/export and backups
- add richer permission policies

## Notes

- Uploaded images are stored locally in `piantala/static/uploads/`.
- The current Home Assistant support stores entity references and values manually. The next iteration can add API-based synchronization.
- The schema auto-updates for the current set of columns on startup and when `init-db` runs, which keeps local iteration simple while the project is still early.
