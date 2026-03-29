# Changelog

All notable changes to Piantala are documented in this file.

The format follows Keep a Changelog and the project uses semantic versioning as a practical guide for release milestones.

## [0.4.0] - 2026-03-29

### Added
- Cultivation types now have a dedicated catalog with shared images, external references, reusable variants, and admin management pages.
- Cultivation nodes now surface cultivation-type reference images and external links directly in their detail view.
- Dedicated node `display` and `map` images can now be deleted again from node detail, node edit, and image-edit screens.

### Changed
- Area nodes now present prospect and map images like sections instead of using the generic gallery-first layout.
- The cultivation-types admin now opens variants from the cultivation edit page, where a compact variant table summarizes what is already available.
- The cultivation-types admin table was tightened and stabilized for more predictable sorting and action-column alignment.

### Fixed
- Section year selectors now include years covered by perennial cultivations, and perennial overlays/cards only appear from their planting year onward.
- Section filter controls are now aligned on a single row, with year and dead-plant controls only shown when relevant.
- Area-based editors now let you drag the full polygon from inside the shape, while corner drags still reshape individual corners.
- Crop/rotate reference lines now stay independent when moving or resizing the crop rectangle.
- Cultivation images can now be removed again after the recent media workflow changes.

## [0.3.5] - 2026-03-29

### Fixed
- Section year selectors now include years covered by perennial cultivations, and perennial overlays/cards only appear from their planting year onward.
- Section filter controls are now aligned on a single row, with year and dead-plant controls only shown when relevant.
- Area-based editors now let you drag the full polygon from inside the shape, while corner drags still reshape individual corners.
- Crop/rotate reference lines now stay independent when moving or resizing the crop rectangle.

## [0.3.4] - 2026-03-28

### Fixed
- New cultivations now save correctly without triggering a `NOT NULL constraint failed: garden_nodes.node_type` error during the initial flush.

## [0.3.3] - 2026-03-28

### Fixed
- Static brand assets now use versioned URLs so remote deployments refresh the icon, stylesheet, and script without stale browser cache.
- The top navigation brand now keeps the icon, app name, and version on a single row with a smaller icon size.

## [0.3.2] - 2026-03-28

### Added
- Irrigation zones can now define additional four-corner map areas while reusing the same texture and color styling as the main zone.
- Storage administration now supports folder-based browsing, thumbnail/list views, clickable file paths, and richer image inventory details.

### Changed
- Edit screens now rely on breadcrumb-style navigation paths instead of the old generic back action.
- Section map presentation now keeps the prospect view clean, moves map filters directly above the map, and keeps irrigation overlays visually consistent.

### Fixed
- Edit-node breadcrumbs now resolve the correct section path instead of duplicating the parent area.
- Additional irrigation areas now save and render correctly, including texture overlays and visibility alongside the main irrigation zone.
- The irrigation-zone and cultivation-position editors now behave more reliably when selecting, dragging, and removing existing overlays.

## [0.3.1] - 2026-03-28

### Added
- Admin runtime visibility now includes an Environment page with server, Python, pip, package, Docker, and disk information.
- The top navigation now shows the Piantala icon and the current application version.
- The cultivation bulk-position editor now supports right-click deletion for existing point markers.

### Changed
- The application version shown in the UI now follows the source tree version from `pyproject.toml`, avoiding stale installed-package metadata.
- Existing photo and node-image edit screens now reuse the crop/rotate preview editor with the already saved image preloaded.

### Fixed
- Existing cultivation markers in the bulk position editor can now be dragged directly instead of being recreated manually.
- The image preview editor initializes more reliably when loading already-saved images or newly selected files.

## [0.3.0] - 2026-03-28

### Added
- Prospect/map image roles are now handled more explicitly across node media flows, including a bulk cultivation-position manager for moving child cultivations from one shared editor.
- New dedicated editors were added for replacing legacy node `display` and `map` images, using the same crop/rotate preview flow as standard uploads.
- Photo editing now supports replacing the underlying image with the same preview, crop, and rotation workflow used during import.

### Changed
- The redundant `Immagine principale` upload area was removed from `modify node`, centralizing image management in the node image list.
- Node image lists in both detail and edit views now surface dedicated node images and standard node photos more consistently.

### Fixed
- The cultivation bulk-position editor now initializes correctly and allows selecting cultivations from the left-hand list.
- Existing nodes such as `Frutteto` can now edit both prospect and map legacy images instead of only the map image.

## [0.2.1] - 2026-03-22

### Added
- Docker data export/import helper scripts for moving the live SQLite database and uploads between hosts.

### Changed
- Annual cultivation views now default to `All years` instead of silently filtering to the current season.

### Fixed
- Annual cultivations cloned into a new year now preserve their existing positions and area polygons by default.
- Existing same-year clones can recover missing positions when cloned again.
- Legacy annual cultivations with no `cultivation_year` are now backfilled automatically on startup, using the planting year when available and `2025` as the legacy fallback.
- User accounts can now be created and managed without an email address across the web admin, CLI, and Docker bootstrap flow.

## [0.2.0] - 2026-03-22

### Added
- Multi-user administration with roles, permissions, audit metadata, login history, and per-user language preferences.
- Admin-managed marker colors, typed external links, activity types, Home Assistant settings, translation editing, and appearance settings.
- Multi-photo node galleries with EXIF date extraction, editable taken dates, default photo selection, and photo timelines.
- Annual cultivation management with cultivation year selection, yearly filtering, cloning across seasons, and lineage history.
- Activity history with configurable activity types, image attachments, and quantity tracking for sowing and harvest.
- Docker deployment support, Docker update helper script, health checks, and persistent volume guidance.

### Changed
- Map-first navigation now supports multiple providers, including Google Maps, OpenStreetMap, and OpenTopoMap.
- Image overlays support point markers, multiple positions, draggable four-corner areas, MDI icons, and shape-specific markers for sections, beds, and plants.
- Home Assistant integration now supports internal URLs, entity discovery from the server, friendly names, image placement, and richer image hover values.
- User email is now optional throughout the admin UI, CLI admin creation, and Docker bootstrap flow.
- Annual cultivation cloning now defaults to the current section and preserves existing overlay positions by default.

### Fixed
- Area overlays now save and reopen with the edited polygon shape instead of reverting visually to rectangles.
- Clone operations now allow the same cultivation title in the same parent across different years.
- Existing same-year clones can inherit missing positions from their source cultivation.
- The area editor drag behavior now works reliably in the browser after fixing multiple frontend interaction issues.

## [0.1.0] - 2026-03-21

### Added
- Initial open-source Flask application scaffold for Piantala with local setup, authentication, map-based node navigation, and Docker-ready structure.
