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
  if (!nodeTypeSelect) {
    return;
  }

  const hideLifecycleFields = nodeTypeSelect.value === "section";
  document.querySelectorAll("[data-section-hidden-field='true']").forEach((field) => {
    field.hidden = hideLifecycleFields;
  });
}

function syncMarkerPreview() {
  const preview = document.getElementById("marker-preview");
  const positionPreview = document.getElementById("node-position-preview");
  if (!preview && !positionPreview) {
    return;
  }

  const nodeTypeSelect = document.querySelector("select[name='node_type']");
  const markerColorSelect = document.getElementById("marker_color_id");
  const markerIconInput = document.getElementById("marker_icon");
  const previewTargets = [
    [preview, document.getElementById("marker-preview-icon")],
    [positionPreview, document.getElementById("node-position-preview-icon")],
  ];
  const selectedOption = markerColorSelect?.selectedOptions?.[0];
  const match = selectedOption?.textContent?.match(/(#[0-9a-fA-F]{6})/);
  const iconValue = (markerIconInput?.value || "").trim();

  previewTargets.forEach(([target, icon]) => {
    if (!target) {
      return;
    }

    ["section", "bed", "plant", "custom", "area"].forEach((nodeType) => {
      target.classList.remove(`image-hotspot-node-${nodeType}`);
    });
    target.classList.add(`image-hotspot-node-${nodeTypeSelect?.value || "custom"}`);
    target.style.setProperty("--hotspot-color", match ? match[1] : "#f28c28");

    if (!icon) {
      return;
    }

    icon.className = "image-hotspot-icon mdi";
    if (iconValue) {
      const normalizedIcon = iconValue.startsWith("mdi-") ? iconValue : `mdi-${iconValue}`;
      target.classList.add("image-hotspot-has-icon");
      icon.hidden = false;
      icon.classList.add(normalizedIcon);
    } else {
      target.classList.remove("image-hotspot-has-icon");
      icon.hidden = true;
    }
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

function syncOverlayEditorPreview(container) {
  const shapeInput = document.getElementById(container.dataset.shapeInput || "");
  const xInput = document.getElementById(container.dataset.xInput || "");
  const yInput = document.getElementById(container.dataset.yInput || "");
  const widthInput = document.getElementById(container.dataset.widthInput || "");
  const heightInput = document.getElementById(container.dataset.heightInput || "");
  const editorLayer = container.querySelector("[data-overlay-editor-layer]");
  const polygon = container.querySelector("[data-overlay-editor-polygon]");
  const handles = Array.from(container.querySelectorAll("[data-overlay-editor-handle]"));
  const pointPreview = document.getElementById("node-position-preview");
  const feedback = document.getElementById(container.dataset.feedbackTarget || "");
  const shape = shapeInput?.value || "point";

  if (!editorLayer || !polygon || !pointPreview) {
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

    pointPreview.hidden = true;
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
  handles.forEach((handle) => {
    handle.hidden = true;
  });
  const x = parseNullablePercent(xInput);
  const y = parseNullablePercent(yInput);
  if (x === null || y === null) {
    pointPreview.hidden = true;
  } else {
    pointPreview.hidden = false;
    pointPreview.style.left = `${formatPercent(x)}%`;
    pointPreview.style.top = `${formatPercent(y)}%`;
  }
  if (feedback) {
    feedback.textContent = "Click the image to place the point.";
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
    const widthInput = document.getElementById(container.dataset.widthInput || "");
    const heightInput = document.getElementById(container.dataset.heightInput || "");
    const handles = Array.from(container.querySelectorAll("[data-overlay-editor-handle]"));
    let dragIndex = null;

    const pointFromMouseEvent = (event) => {
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

      const point = pointFromMouseEvent(event);
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
        updateImagePickerCoordinates(container, point.x, point.y);
      }

      syncOverlayEditorPreview(container);
    });

    handles.forEach((handle) => {
      handle.addEventListener("mousedown", (event) => {
        dragIndex = Number.parseInt(handle.dataset.overlayEditorHandle || "-1", 10);
        event.preventDefault();
      });
    });

    document.addEventListener("mousemove", (event) => {
      if (dragIndex === null) {
        return;
      }
      const point = pointFromMouseEvent(event);
      if (!point) {
        return;
      }
      const points = readOverlayPolygon(container);
      if (!points[dragIndex]) {
        return;
      }
      points[dragIndex] = point;
      writeOverlayPolygon(points);
      syncOverlayEditorPreview(container);
    });

    document.addEventListener("mouseup", () => {
      dragIndex = null;
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
    syncMarkerPreview();
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
initOverlayEditors();
