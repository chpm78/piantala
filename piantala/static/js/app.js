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
  if (!preview) {
    return;
  }

  const nodeTypeSelect = document.querySelector("select[name='node_type']");
  const markerColorSelect = document.getElementById("marker_color_id");
  const markerIconInput = document.getElementById("marker_icon");
  const previewIcon = document.getElementById("marker-preview-icon");

  ["section", "bed", "plant", "custom", "area"].forEach((nodeType) => {
    preview.classList.remove(`image-hotspot-node-${nodeType}`);
  });
  preview.classList.add(`image-hotspot-node-${nodeTypeSelect?.value || "custom"}`);

  const selectedOption = markerColorSelect?.selectedOptions?.[0];
  const match = selectedOption?.textContent?.match(/(#[0-9a-fA-F]{6})/);
  preview.style.setProperty("--hotspot-color", match ? match[1] : "#f28c28");

  const iconValue = (markerIconInput?.value || "").trim();
  if (previewIcon) {
    previewIcon.className = "image-hotspot-icon mdi";
    if (iconValue) {
      const normalizedIcon = iconValue.startsWith("mdi-") ? iconValue : `mdi-${iconValue}`;
      preview.classList.add("image-hotspot-has-icon");
      previewIcon.hidden = false;
      previewIcon.classList.add(normalizedIcon);
    } else {
      preview.classList.remove("image-hotspot-has-icon");
      previewIcon.hidden = true;
    }
  }
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
};

if (window.google?.maps) {
  window.initPiantalaGoogleMaps();
}

if (window.L) {
  window.initPiantalaLeafletMaps();
}

syncProviderPanels();
syncNodeTypeFields();
