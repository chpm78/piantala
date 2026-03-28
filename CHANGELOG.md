# Changelog

All notable changes to Piantala are documented in this file.

The format follows Keep a Changelog and the project uses semantic versioning as a practical guide for release milestones.

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
