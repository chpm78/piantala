# Changelog

All notable changes to Piantala are documented in this file.

The format follows Keep a Changelog and the project uses semantic versioning as a practical guide for release milestones.

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
