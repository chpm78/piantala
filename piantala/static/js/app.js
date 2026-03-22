function updateImagePickerCoordinates(container, x, y) {
  const xInput = document.getElementById(container.dataset.xInput || "");
  const yInput = document.getElementById(container.dataset.yInput || "");
  if (xInput) {
    xInput.value = x.toFixed(2);
  }
  if (yInput) {
    yInput.value = y.toFixed(2);
  }

  const feedbackTarget = container.dataset.feedbackTarget;
  if (feedbackTarget) {
    const feedback = document.getElementById(feedbackTarget);
    if (feedback) {
      feedback.textContent = `Estimated coordinates: X ${x.toFixed(2)}%, Y ${y.toFixed(2)}%`;
    }
  }
}

function syncProviderPanels() {
  const providerSelect = document.querySelector("[data-map-provider-select='true']");
  if (!providerSelect) {
    return;
  }

  const selectedProvider = providerSelect.value;
  document.querySelectorAll("[data-provider-panel]").forEach((panel) => {
    const supportedProviders = (panel.dataset.providerPanel || "").split(/\s+/).filter(Boolean);
    panel.classList.toggle("is-active", supportedProviders.includes(selectedProvider));
  });
}

function syncNodeTypeFields() {
  const nodeTypeSelect = document.querySelector("select[name='node_type']");
  const lifeCycleSelect = document.querySelector("select[name='life_cycle']");
  if (!nodeTypeSelect) {
    return;
  }

  const hideLifecycleFields = nodeTypeSelect.value === "section";
  document.querySelectorAll("[data-section-hidden-field='true']").forEach((field) => {
    field.hidden = hideLifecycleFields;
  });

  const showAnnualFields = !hideLifecycleFields && lifeCycleSelect?.value === "annual";
  document.querySelectorAll("[data-annual-only-field='true']").forEach((field) => {
    field.hidden = !showAnnualFields;
  });
}

function syncCultivationYearFromPlantingDate() {
  const nodeTypeSelect = document.querySelector("select[name='node_type']");
  const lifeCycleSelect = document.querySelector("select[name='life_cycle']");
  const plantingDateInput = document.getElementById("planting_date");
  const cultivationYearInput = document.getElementById("cultivation_year");
  if (!plantingDateInput || !cultivationYearInput) {
    return;
  }

  const isAnnualCultivation =
    nodeTypeSelect?.value !== "section" && lifeCycleSelect?.value === "annual";
  if (!isAnnualCultivation) {
    cultivationYearInput.removeAttribute("min");
    return;
  }

  const plantingYear = Number.parseInt((plantingDateInput.value || "").slice(0, 4), 10);
  if (!Number.isFinite(plantingYear)) {
    cultivationYearInput.removeAttribute("min");
    return;
  }

  cultivationYearInput.min = String(plantingYear);
  const currentValue = cultivationYearInput.value.trim();
  if (!currentValue || cultivationYearInput.dataset.autoFilled === "true") {
    cultivationYearInput.value = String(plantingYear);
    cultivationYearInput.dataset.autoFilled = "true";
  }
}

function syncMarkerPreview() {
  const preview = document.getElementById("marker-preview");
  if (!preview) {
    return;
  }

  const nodeTypeSelect = document.querySelector("select[name='node_type']");
  const markerColorSelect = document.getElementById("marker_color_id");
  const markerIconInput = document.getElementById("marker_icon");
  const selectedOption = markerColorSelect?.selectedOptions?.[0];
  const match = selectedOption?.textContent?.match(/(#[0-9a-fA-F]{6})/);
  const iconValue = (markerIconInput?.value || "").trim();

  ["section", "bed", "plant", "custom", "area"].forEach((nodeType) => {
    preview.classList.remove(`image-hotspot-node-${nodeType}`);
  });
  preview.classList.add(`image-hotspot-node-${nodeTypeSelect?.value || "custom"}`);
  preview.style.setProperty("--hotspot-color", match ? match[1] : "#f28c28");

  const icon = document.getElementById("marker-preview-icon");
  if (icon) {
    icon.className = "image-hotspot-icon mdi";
    if (iconValue) {
      const normalizedIcon = iconValue.startsWith("mdi-") ? iconValue : `mdi-${iconValue}`;
      preview.classList.add("image-hotspot-has-icon");
      icon.hidden = false;
      icon.classList.add(normalizedIcon);
    } else {
      preview.classList.remove("image-hotspot-has-icon");
      icon.hidden = true;
    }
  }

  document.querySelectorAll("[data-overlay-editor='true']").forEach((container) => {
    syncOverlayEditorPreview(container);
  });
}

function formatPercent(value) {
  return Number.parseFloat(value).toFixed(2);
}

function parseNullablePercent(input) {
  if (!input) {
    return null;
  }
  const parsed = Number.parseFloat(input.value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildDefaultPolygon(centerX, centerY, width, height) {
  const halfWidth = (width || 18) / 2;
  const halfHeight = (height || 12) / 2;
  return [
    {
      x: Math.max(0, Math.min(100, centerX - halfWidth)),
      y: Math.max(0, Math.min(100, centerY - halfHeight)),
    },
    {
      x: Math.max(0, Math.min(100, centerX + halfWidth)),
      y: Math.max(0, Math.min(100, centerY - halfHeight)),
    },
    {
      x: Math.max(0, Math.min(100, centerX + halfWidth)),
      y: Math.max(0, Math.min(100, centerY + halfHeight)),
    },
    {
      x: Math.max(0, Math.min(100, centerX - halfWidth)),
      y: Math.max(0, Math.min(100, centerY + halfHeight)),
    },
  ];
}

function readOverlayPolygon(container) {
  const points = [];
  for (let index = 1; index <= 4; index += 1) {
    const x = parseNullablePercent(document.getElementById(`area_corner_${index}_x`));
    const y = parseNullablePercent(document.getElementById(`area_corner_${index}_y`));
    if (x === null || y === null) {
      return [];
    }
    points.push({ x, y });
  }
  return points;
}

function writeOverlayPolygon(points) {
  points.forEach((point, index) => {
    const xInput = document.getElementById(`area_corner_${index + 1}_x`);
    const yInput = document.getElementById(`area_corner_${index + 1}_y`);
    if (xInput) {
      xInput.value = formatPercent(point.x);
    }
    if (yInput) {
      yInput.value = formatPercent(point.y);
    }
  });

  const xInput = document.getElementById("map_x");
  const yInput = document.getElementById("map_y");
  if (xInput && yInput && points.length) {
    const centerX = points.reduce((sum, point) => sum + point.x, 0) / points.length;
    const centerY = points.reduce((sum, point) => sum + point.y, 0) / points.length;
    xInput.value = formatPercent(centerX);
    yInput.value = formatPercent(centerY);
  }
}

function createPointMarkerElement(position, index) {
  const nodeType = document.querySelector("select[name='node_type']")?.value || "custom";
  const markerColorSelect = document.getElementById("marker_color_id");
  const markerIconInput = document.getElementById("marker_icon");
  const selectedOption = markerColorSelect?.selectedOptions?.[0];
  const match = selectedOption?.textContent?.match(/(#[0-9a-fA-F]{6})/);
  const iconValue = (markerIconInput?.value || "").trim();

  const button = document.createElement("button");
  button.type = "button";
  button.className = `image-hotspot image-hotspot-static image-hotspot-point image-hotspot-node-${nodeType} overlay-editor-point`;
  button.style.left = `${formatPercent(position.x)}%`;
  button.style.top = `${formatPercent(position.y)}%`;
  button.style.setProperty("--hotspot-color", match ? match[1] : "#f28c28");
  button.dataset.pointIndex = String(index);
  button.setAttribute("aria-label", `Point position ${index + 1}`);

  if (iconValue) {
    const normalizedIcon = iconValue.startsWith("mdi-") ? iconValue : `mdi-${iconValue}`;
    button.classList.add("image-hotspot-has-icon");
    const icon = document.createElement("span");
    icon.className = `image-hotspot-icon mdi ${normalizedIcon}`;
    icon.setAttribute("aria-hidden", "true");
    button.appendChild(icon);
  } else {
    const badge = document.createElement("span");
    badge.className = "overlay-editor-point-label";
    badge.textContent = String(index + 1);
    button.appendChild(badge);
  }

  return button;
}

function readPointPositionsFromHidden(container) {
  const positionsInput = document.getElementById(container.dataset.positionsInput || "");
  const xInput = document.getElementById(container.dataset.xInput || "");
  const yInput = document.getElementById(container.dataset.yInput || "");
  if (positionsInput?.value) {
    try {
      const parsed = JSON.parse(positionsInput.value);
      if (Array.isArray(parsed)) {
        return parsed
          .map((item) => ({
            x: parseFloatOrDefault(item?.x, null),
            y: parseFloatOrDefault(item?.y, null),
          }))
          .filter((item) => item.x !== null && item.y !== null);
      }
    } catch (error) {
      // Ignore malformed payload and fall back to the visible inputs.
    }
  }

  const x = parseNullablePercent(xInput);
  const y = parseNullablePercent(yInput);
  return x !== null && y !== null ? [{ x, y }] : [];
}

function writePointPositions(container, positions) {
  const positionsInput = document.getElementById(container.dataset.positionsInput || "");
  const xInput = document.getElementById(container.dataset.xInput || "");
  const yInput = document.getElementById(container.dataset.yInput || "");
  const normalized = positions.map((position) => ({
    x: Number.parseFloat(formatPercent(position.x)),
    y: Number.parseFloat(formatPercent(position.y)),
  }));

  if (positionsInput) {
    positionsInput.value = JSON.stringify(normalized);
  }
  if (xInput) {
    xInput.value = normalized.length ? formatPercent(normalized[0].x) : "";
  }
  if (yInput) {
    yInput.value = normalized.length ? formatPercent(normalized[0].y) : "";
  }
}

function syncOverlayEditorPreview(container) {
  const shapeInput = document.getElementById(container.dataset.shapeInput || "");
  const xInput = document.getElementById(container.dataset.xInput || "");
  const yInput = document.getElementById(container.dataset.yInput || "");
  const widthInput = document.getElementById(container.dataset.widthInput || "");
  const heightInput = document.getElementById(container.dataset.heightInput || "");
  const editorLayer = container.querySelector("[data-overlay-editor-layer]");
  const polygon = container.querySelector("[data-overlay-editor-polygon]");
  const handles = Array.from(container.querySelectorAll("[data-overlay-editor-handle]"));
  const pointLayer = container.querySelector("[data-point-positions-layer]");
  const pointPanel = container.parentElement?.querySelector("[data-point-positions-panel]");
  const pointList = pointPanel?.querySelector("[data-point-positions-list]");
  const feedback = document.getElementById(container.dataset.feedbackTarget || "");
  const shape = shapeInput?.value || "point";

  if (!editorLayer || !polygon || !pointLayer) {
    return;
  }

  if (shape === "area") {
    let points = readOverlayPolygon(container);
    const centerX = parseNullablePercent(xInput);
    const centerY = parseNullablePercent(yInput);
    const width = parseNullablePercent(widthInput) ?? 18;
    const height = parseNullablePercent(heightInput) ?? 12;

    if (!points.length && centerX !== null && centerY !== null) {
      points = buildDefaultPolygon(centerX, centerY, width, height);
      writeOverlayPolygon(points);
    }

    pointLayer.innerHTML = "";
    pointLayer.hidden = true;
    if (pointList) {
      pointList.innerHTML = "";
    }
    editorLayer.hidden = !points.length;
    polygon.setAttribute(
      "points",
      points.map((point) => `${formatPercent(point.x)},${formatPercent(point.y)}`).join(" "),
    );
    handles.forEach((handle, index) => {
      const point = points[index];
      handle.hidden = !point;
      if (!point) {
        return;
      }
      handle.style.left = `${formatPercent(point.x)}%`;
      handle.style.top = `${formatPercent(point.y)}%`;
    });

    if (feedback) {
      feedback.textContent = points.length
        ? "Drag the four corners to shape the area."
        : "Click the image once to place a starting area, then drag the corners.";
    }
    return;
  }

  editorLayer.hidden = true;
  pointLayer.hidden = false;
  handles.forEach((handle) => {
    handle.hidden = true;
  });
  const positions = readPointPositionsFromHidden(container);
  pointLayer.innerHTML = "";
  if (pointList) {
    pointList.innerHTML = "";
  }
  positions.forEach((position, index) => {
    pointLayer.appendChild(createPointMarkerElement(position, index));
    if (pointList) {
      const item = document.createElement("div");
      item.className = "point-positions-item";
      item.innerHTML = `<span>${index + 1}. X ${formatPercent(position.x)}%, Y ${formatPercent(position.y)}%</span>`;
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "button button-secondary button-small";
      removeButton.textContent = pointPanel?.dataset.removeLabel || "Delete";
      removeButton.dataset.removePointIndex = String(index);
      item.appendChild(removeButton);
      pointList.appendChild(item);
    }
  });
  if (feedback) {
    feedback.textContent = "Click the image to add a point. Drag any point to move it.";
  }
}

function initOverlayEditors() {
  document.querySelectorAll("[data-overlay-editor='true']").forEach((container) => {
    if (container.dataset.overlayEditorReady === "true") {
      syncOverlayEditorPreview(container);
      return;
    }
    container.dataset.overlayEditorReady = "true";

    const image = container.querySelector("img");
    const shapeInput = document.getElementById(container.dataset.shapeInput || "");
    const xInput = document.getElementById(container.dataset.xInput || "");
    const yInput = document.getElementById(container.dataset.yInput || "");
    const widthInput = document.getElementById(container.dataset.widthInput || "");
    const heightInput = document.getElementById(container.dataset.heightInput || "");
    const pointPanel = container.parentElement?.querySelector("[data-point-positions-panel]");
    const pointList = pointPanel?.querySelector("[data-point-positions-list]");
    const handles = Array.from(container.querySelectorAll("[data-overlay-editor-handle]"));
    let detachActiveDragListeners = null;

    const pointFromPointerEvent = (event) => {
      if (!image) {
        return null;
      }
      const rect = image.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      ) {
        return null;
      }
      return {
        x: ((event.clientX - rect.left) / rect.width) * 100,
        y: ((event.clientY - rect.top) / rect.height) * 100,
      };
    };

    container.addEventListener("click", (event) => {
      if (event.target.closest("a, button, input, textarea, select, label")) {
        return;
      }

      const point = pointFromPointerEvent(event);
      if (!point) {
        return;
      }

      if ((shapeInput?.value || "point") === "area") {
        if (!readOverlayPolygon(container).length) {
          const width = parseNullablePercent(widthInput) ?? 18;
          const height = parseNullablePercent(heightInput) ?? 12;
          writeOverlayPolygon(buildDefaultPolygon(point.x, point.y, width, height));
        }
      } else {
        const positions = readPointPositionsFromHidden(container);
        positions.push(point);
        writePointPositions(container, positions);
      }

      syncOverlayEditorPreview(container);
    });

    const startDrag = (pointerId, onMove) => {
      if (detachActiveDragListeners) {
        detachActiveDragListeners();
      }

      const handlePointerMove = (moveEvent) => {
        if (moveEvent.pointerId !== pointerId) {
          return;
        }
        const point = pointFromPointerEvent(moveEvent);
        if (!point) {
          return;
        }
        onMove(point);
      };

      const stopDrag = (endEvent) => {
        if (endEvent.pointerId !== pointerId) {
          return;
        }
        if (detachActiveDragListeners) {
          detachActiveDragListeners();
        }
      };

      detachActiveDragListeners = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", stopDrag);
        window.removeEventListener("pointercancel", stopDrag);
        detachActiveDragListeners = null;
      };

      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", stopDrag);
      window.addEventListener("pointercancel", stopDrag);
    };

    handles.forEach((handle) => {
      handle.addEventListener("pointerdown", (event) => {
        const handleIndex = Number.parseInt(handle.dataset.overlayEditorHandle || "-1", 10);
        if (handleIndex < 0) {
          return;
        }
        if (typeof handle.setPointerCapture === "function") {
          handle.setPointerCapture(event.pointerId);
        }
        startDrag(event.pointerId, (point) => {
          const points = readOverlayPolygon(container);
          if (!points[handleIndex]) {
            return;
          }
          points[handleIndex] = point;
          writeOverlayPolygon(points);
          syncOverlayEditorPreview(container);
        });
        event.preventDefault();
        event.stopPropagation();
      });
    });

    container.addEventListener("pointerdown", (event) => {
      const point = event.target.closest("[data-point-index]");
      if (!point) {
        return;
      }
      const pointIndex = Number.parseInt(point.dataset.pointIndex || "-1", 10);
      if (pointIndex < 0) {
        return;
      }
      if (typeof point.setPointerCapture === "function") {
        point.setPointerCapture(event.pointerId);
      }
      startDrag(event.pointerId, (position) => {
        const positions = readPointPositionsFromHidden(container);
        if (!positions[pointIndex]) {
          return;
        }
        positions[pointIndex] = position;
        writePointPositions(container, positions);
        syncOverlayEditorPreview(container);
      });
      event.preventDefault();
    });

    container.addEventListener("dragstart", (event) => {
      event.preventDefault();
    });

    pointList?.addEventListener("click", (event) => {
      const removeButton = event.target.closest("[data-remove-point-index]");
      if (!removeButton) {
        return;
      }
      const removeIndex = Number.parseInt(removeButton.dataset.removePointIndex || "-1", 10);
      const positions = readPointPositionsFromHidden(container);
      positions.splice(removeIndex, 1);
      writePointPositions(container, positions);
      syncOverlayEditorPreview(container);
    });

    if (shapeInput) {
      shapeInput.addEventListener("change", () => {
        if (shapeInput.value !== "area") {
          for (let index = 1; index <= 4; index += 1) {
            const xInput = document.getElementById(`area_corner_${index}_x`);
            const yInput = document.getElementById(`area_corner_${index}_y`);
            if (xInput) {
              xInput.value = "";
            }
            if (yInput) {
              yInput.value = "";
            }
          }
        }
        syncOverlayEditorPreview(container);
      });
    }

    [xInput, yInput].forEach((input) => {
      input?.addEventListener("change", () => {
        if ((shapeInput?.value || "point") !== "point") {
          return;
        }
        const x = parseNullablePercent(xInput);
        const y = parseNullablePercent(yInput);
        if (x === null || y === null) {
          return;
        }
        const positions = readPointPositionsFromHidden(container);
        if (positions.length) {
          positions[0] = { x, y };
        } else {
          positions.push({ x, y });
        }
        writePointPositions(container, positions);
        syncOverlayEditorPreview(container);
      });
    });

    syncOverlayEditorPreview(container);
  });
}

document.addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-confirm]");
  if (deleteButton && !window.confirm(deleteButton.dataset.confirm)) {
    event.preventDefault();
    return;
  }

  const picker = event.target.closest("[data-coordinate-picker='image']");
  if (!picker) {
    return;
  }

  if (picker.dataset.overlayEditor === "true") {
    return;
  }

  if (event.target.closest("a, button, input, textarea, select, label")) {
    return;
  }

  const image = picker.querySelector("img");
  if (!image) {
    return;
  }

  const rect = image.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  ) {
    return;
  }

  const x = ((event.clientX - rect.left) / rect.width) * 100;
  const y = ((event.clientY - rect.top) / rect.height) * 100;
  updateImagePickerCoordinates(picker, x, y);
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-map-provider-select='true']")) {
    syncProviderPanels();
  }

  if (event.target.matches("select[name='node_type']")) {
    syncNodeTypeFields();
    syncCultivationYearFromPlantingDate();
    syncMarkerPreview();
  }

  if (event.target.matches("select[name='life_cycle']")) {
    syncNodeTypeFields();
    syncCultivationYearFromPlantingDate();
  }

  if (event.target.matches("#planting_date")) {
    syncCultivationYearFromPlantingDate();
  }

  if (event.target.matches("#cultivation_year")) {
    event.target.dataset.autoFilled = "false";
  }

  if (event.target.matches("#overlay_shape")) {
    initOverlayEditors();
  }

  if (event.target.matches("#marker_color_id")) {
    syncMarkerPreview();
  }

  if (event.target.matches("#marker_icon")) {
    syncMarkerPreview();
  }
});

function parseFloatOrDefault(value, fallback) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseIntOrDefault(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function initOverviewMap(element) {
  const center = {
    lat: parseFloatOrDefault(element.dataset.centerLat, 0),
    lng: parseFloatOrDefault(element.dataset.centerLng, 0),
  };
  const zoom = parseIntOrDefault(element.dataset.zoom, 19);
  const locations = JSON.parse(element.dataset.locations || "[]");

  const map = new window.google.maps.Map(element, {
    center,
    zoom,
    mapTypeId: "hybrid",
  });

  locations.forEach((location) => {
    const marker = new window.google.maps.Marker({
      map,
      position: { lat: location.lat, lng: location.lng },
      title: location.title,
    });
    marker.addListener("click", () => {
      window.location.href = location.url;
    });
  });
}

function initPickerMap(element) {
  const latInput = document.getElementById(element.dataset.latInput || "");
  const lngInput = document.getElementById(element.dataset.lngInput || "");
  const initialLat = parseFloatOrDefault(
    latInput?.value || element.dataset.centerLat,
    0,
  );
  const initialLng = parseFloatOrDefault(
    lngInput?.value || element.dataset.centerLng,
    0,
  );
  const zoom = parseIntOrDefault(element.dataset.zoom, 19);
  const initialPosition = { lat: initialLat, lng: initialLng };

  const map = new window.google.maps.Map(element, {
    center: initialPosition,
    zoom,
    mapTypeId: "hybrid",
  });

  const marker = new window.google.maps.Marker({
    map,
    position: initialPosition,
    draggable: true,
  });

  const updateInputs = (latLng) => {
    if (latInput) {
      latInput.value = latLng.lat().toFixed(6);
    }
    if (lngInput) {
      lngInput.value = latLng.lng().toFixed(6);
    }
  };

  map.addListener("click", (event) => {
    marker.setPosition(event.latLng);
    updateInputs(event.latLng);
  });

  marker.addListener("dragend", () => {
    const position = marker.getPosition();
    if (position) {
      updateInputs(position);
    }
  });
}

function getLeafletTileConfig(provider) {
  if (provider === "opentopomap") {
    return {
      url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
      options: {
        maxZoom: 19,
        attribution:
          'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | Map style: &copy; <a href="https://opentopomap.org/about">OpenTopoMap</a> (CC-BY-SA)',
      },
    };
  }

  return {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    options: {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
  };
}

function initLeafletOverviewMap(element) {
  const center = [
    parseFloatOrDefault(element.dataset.centerLat, 0),
    parseFloatOrDefault(element.dataset.centerLng, 0),
  ];
  const zoom = parseIntOrDefault(element.dataset.zoom, 19);
  const locations = JSON.parse(element.dataset.locations || "[]");
  const provider = element.dataset.tileProvider || "openstreetmap";
  const tileConfig = getLeafletTileConfig(provider);

  const map = window.L.map(element).setView(center, zoom);
  window.L.tileLayer(tileConfig.url, tileConfig.options).addTo(map);

  locations.forEach((location) => {
    const marker = window.L.marker([location.lat, location.lng]).addTo(map);
    marker.bindPopup(location.title);
    marker.on("click", () => {
      window.location.href = location.url;
    });
  });
}

function initLeafletPickerMap(element) {
  const latInput = document.getElementById(element.dataset.latInput || "");
  const lngInput = document.getElementById(element.dataset.lngInput || "");
  const provider = element.dataset.tileProvider || "openstreetmap";
  const tileConfig = getLeafletTileConfig(provider);
  const lat = parseFloatOrDefault(latInput?.value || element.dataset.centerLat, 0);
  const lng = parseFloatOrDefault(lngInput?.value || element.dataset.centerLng, 0);
  const zoom = parseIntOrDefault(element.dataset.zoom, 19);

  const map = window.L.map(element).setView([lat, lng], zoom);
  window.L.tileLayer(tileConfig.url, tileConfig.options).addTo(map);
  const marker = window.L.marker([lat, lng], { draggable: true }).addTo(map);

  const updateInputs = (latlng) => {
    if (latInput) {
      latInput.value = latlng.lat.toFixed(6);
    }
    if (lngInput) {
      lngInput.value = latlng.lng.toFixed(6);
    }
  };

  map.on("click", (event) => {
    marker.setLatLng(event.latlng);
    updateInputs(event.latlng);
  });

  marker.on("dragend", () => {
    updateInputs(marker.getLatLng());
  });
}

window.initPiantalaGoogleMaps = function initPiantalaGoogleMaps() {
  document.querySelectorAll("[data-google-map]").forEach((element) => {
    if (element.dataset.mapReady === "true") {
      return;
    }
    element.dataset.mapReady = "true";

    if (element.dataset.googleMap === "overview") {
      initOverviewMap(element);
      return;
    }

    if (element.dataset.googleMap === "picker") {
      initPickerMap(element);
    }
  });
};

window.initPiantalaLeafletMaps = function initPiantalaLeafletMaps() {
  if (!window.L) {
    return;
  }

  document.querySelectorAll("[data-leaflet-map]").forEach((element) => {
    if (element.dataset.mapReady === "true") {
      return;
    }
    element.dataset.mapReady = "true";

    if (element.dataset.leafletMap === "overview") {
      initLeafletOverviewMap(element);
      return;
    }

    if (element.dataset.leafletMap === "picker") {
      initLeafletPickerMap(element);
    }
  });
};

window.initPiantalaNodeTypeFields = function initPiantalaNodeTypeFields() {
  syncNodeTypeFields();
  syncMarkerPreview();
  initOverlayEditors();
};

if (window.google?.maps) {
  window.initPiantalaGoogleMaps();
}

if (window.L) {
  window.initPiantalaLeafletMaps();
}

syncProviderPanels();
syncNodeTypeFields();
syncCultivationYearFromPlantingDate();
initOverlayEditors();
