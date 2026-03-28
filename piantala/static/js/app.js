/**
 * Update hidden coordinate fields and visible feedback for image click pickers.
 *
 * @param {HTMLElement} container Picker container holding field references.
 * @param {number} x Horizontal image percentage.
 * @param {number} y Vertical image percentage.
 */
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

/**
 * Show only the settings panel that matches the selected homepage map provider.
 */
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

/**
 * Toggle node form fields based on node type and life cycle.
 */
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

/**
 * Keep the cultivation year aligned with the planting date for annual records.
 */
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

/**
 * Refresh the marker preview shown in the node editor.
 */
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

/**
 * Format a percentage value for storage and UI display.
 *
 * @param {number|string} value Percentage value to format.
 * @returns {string}
 */
function formatPercent(value) {
  return Number.parseFloat(value).toFixed(2);
}

/**
 * Parse a numeric percentage from an input field.
 *
 * @param {HTMLInputElement|null} input Input element holding a percentage value.
 * @returns {number|null}
 */
function parseNullablePercent(input) {
  if (!input) {
    return null;
  }
  const parsed = Number.parseFloat(input.value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Create a default four-corner polygon around a center point.
 *
 * @param {number} centerX Horizontal center percentage.
 * @param {number} centerY Vertical center percentage.
 * @param {number} width Area width percentage.
 * @param {number} height Area height percentage.
 * @returns {Array<{x: number, y: number}>}
 */
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

/**
 * Read the four stored area corners from the node editor form.
 *
 * @param {HTMLElement} container Overlay editor container.
 * @returns {Array<{x: number, y: number}>}
 */
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

/**
 * Write a polygon back to the hidden area corner fields.
 *
 * @param {Array<{x: number, y: number}>} points Polygon points to persist.
 */
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

/**
 * Create one draggable point marker preview for the overlay editor.
 *
 * @param {{x: number, y: number}} position Marker position as image percentages.
 * @param {number} index Zero-based point index.
 * @returns {HTMLButtonElement}
 */
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

/**
 * Read point hotspot positions from the hidden JSON field or fallback inputs.
 *
 * @param {HTMLElement} container Overlay editor container.
 * @returns {Array<{x: number, y: number}>}
 */
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

/**
 * Persist point hotspot positions back into the node form fields.
 *
 * @param {HTMLElement} container Overlay editor container.
 * @param {Array<{x: number, y: number}>} positions Point positions to store.
 */
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

/**
 * Redraw the overlay editor preview for point or area mode.
 *
 * @param {HTMLElement} container Overlay editor container.
 */
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

/**
 * Wire drag-and-drop behavior for all overlay editors on the page.
 */
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

/**
 * Create a draggable point marker for the bulk cultivation position editor.
 *
 * @param {{node_type: string, marker_color: string, marker_icon: string}} child Child display metadata.
 * @param {{x: number, y: number}} position Marker position as image percentages.
 * @param {number} index Zero-based point index.
 * @param {boolean} selected Whether the child is currently selected in the editor.
 * @returns {HTMLButtonElement}
 */
function createManagedPointMarkerElement(child, position, index, selected) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `image-hotspot image-hotspot-static image-hotspot-point image-hotspot-node-${child.node_type || "custom"} overlay-editor-point cultivation-manager-point`;
  if (selected) {
    button.classList.add("is-selected");
  }
  button.style.left = `${formatPercent(position.x)}%`;
  button.style.top = `${formatPercent(position.y)}%`;
  button.style.setProperty("--hotspot-color", child.marker_color || "#f28c28");
  button.dataset.pointIndex = String(index);
  button.setAttribute("aria-label", `${child.title || "Cultivation"} point ${index + 1}`);

  if (child.marker_icon) {
    button.classList.add("image-hotspot-has-icon");
    const icon = document.createElement("span");
    icon.className = `image-hotspot-icon mdi ${child.marker_icon}`;
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

/**
 * Initialize the shared cultivation-position manager used to move many children from one page.
 */
function initCultivationPositionManagers() {
  document.querySelectorAll("[data-cultivation-position-manager='true']").forEach((container) => {
    if (container.dataset.positionsReady === "true") {
      return;
    }
    container.dataset.positionsReady = "true";

    const stateInput = container.querySelector("[data-cultivation-state-input='true']");
    const image = container.querySelector("[data-cultivation-image='true']");
    const staticLayer = container.querySelector("[data-cultivation-static-layer='true']");
    const editorLayer = container.querySelector("[data-cultivation-editor-layer='true']");
    const polygon = container.querySelector("[data-cultivation-editor-polygon='true']");
    const handles = Array.from(container.querySelectorAll("[data-cultivation-editor-handle]"));
    const pointLayer = container.querySelector("[data-cultivation-point-layer='true']");
    const pointPanel = container.querySelector("[data-cultivation-point-panel='true']");
    const pointList = container.querySelector("[data-cultivation-point-list='true']");
    const selectedTitle = container.querySelector("[data-cultivation-selected-title='true']");
    const helpText = container.querySelector("[data-cultivation-help='true']");
    const listButtons = Array.from(container.querySelectorAll("[data-cultivation-select='true']"));

    let children = [];
    try {
      children = JSON.parse(stateInput?.value || "[]");
    } catch (error) {
      children = [];
    }
    if (!Array.isArray(children) || !image || !staticLayer || !editorLayer || !polygon || !pointLayer) {
      return;
    }

    let selectedChildId = Number.parseInt(container.dataset.selectedChildId || "", 10);
    if (!Number.isFinite(selectedChildId)) {
      selectedChildId = Number.parseInt(children[0]?.id, 10);
    }
    let detachActiveDragListeners = null;

    const findChild = () =>
      children.find((child) => Number.parseInt(child.id, 10) === Number.parseInt(selectedChildId, 10)) || children[0];

    const writeState = () => {
      if (stateInput) {
        stateInput.value = JSON.stringify(children);
      }
    };

    const pointFromPointerEvent = (event) => {
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
        x: Math.max(0, Math.min(100, ((event.clientX - rect.left) / rect.width) * 100)),
        y: Math.max(0, Math.min(100, ((event.clientY - rect.top) / rect.height) * 100)),
      };
    };

    const updateSelectionUi = () => {
      const current = findChild();
      listButtons.forEach((button) => {
        button.classList.toggle(
          "is-selected",
          Number.parseInt(button.dataset.childId || "", 10) === Number.parseInt(current?.id, 10),
        );
      });
      if (selectedTitle) {
        selectedTitle.textContent = current?.title || "";
      }
      if (helpText) {
        helpText.textContent = current?.overlay_shape === "area"
          ? (container.dataset.areaHelp || "Drag the four corners to reshape the selected cultivation.")
          : (container.dataset.pointHelp || "Click the map to add a point, then drag markers to fine-tune them.");
      }
    };

    const renderStaticLayer = () => {
      staticLayer.innerHTML = "";
      const current = findChild();
      children.forEach((child) => {
        const isSelected = Number.parseInt(child.id, 10) === Number.parseInt(current?.id, 10);
        if (child.overlay_shape === "area" && Array.isArray(child.polygon) && child.polygon.length === 4) {
          const overlay = document.createElement("div");
          overlay.className = "cultivation-manager-area";
          if (isSelected) {
            overlay.classList.add("is-selected");
          }
          overlay.innerHTML = `
            <svg class="image-hotspot-area-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <polygon class="image-hotspot-area-polygon" points="${child.polygon.map((point) => `${formatPercent(point.x)},${formatPercent(point.y)}`).join(" ")}"></polygon>
            </svg>
          `;
          staticLayer.appendChild(overlay);
          return;
        }

        (Array.isArray(child.points) ? child.points : []).forEach((position, index) => {
          const marker = createManagedPointMarkerElement(child, position, index, isSelected);
          marker.tabIndex = -1;
          marker.disabled = true;
          staticLayer.appendChild(marker);
        });
      });
    };

    const renderEditor = () => {
      const current = findChild();
      updateSelectionUi();
      renderStaticLayer();
      if (!current) {
        editorLayer.hidden = true;
        pointLayer.hidden = true;
        if (pointList) {
          pointList.innerHTML = "";
        }
        return;
      }

      if (current.overlay_shape === "area") {
        const polygonPoints = Array.isArray(current.polygon) ? current.polygon : [];
        pointLayer.innerHTML = "";
        pointLayer.hidden = true;
        if (pointPanel) {
          pointPanel.hidden = true;
        }
        editorLayer.hidden = !polygonPoints.length;
        polygon.setAttribute(
          "points",
          polygonPoints.map((point) => `${formatPercent(point.x)},${formatPercent(point.y)}`).join(" "),
        );
        handles.forEach((handle, index) => {
          const point = polygonPoints[index];
          handle.hidden = !point;
          if (point) {
            handle.style.left = `${formatPercent(point.x)}%`;
            handle.style.top = `${formatPercent(point.y)}%`;
          }
        });
        writeState();
        return;
      }

      editorLayer.hidden = true;
      handles.forEach((handle) => {
        handle.hidden = true;
      });
      pointLayer.hidden = false;
      pointLayer.innerHTML = "";
      if (pointPanel) {
        pointPanel.hidden = false;
      }
      if (pointList) {
        pointList.innerHTML = "";
      }
      (Array.isArray(current.points) ? current.points : []).forEach((position, index) => {
        pointLayer.appendChild(createManagedPointMarkerElement(current, position, index, true));
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
          pointList?.appendChild(item);
        }
      });
      writeState();
    };

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

    container.addEventListener("click", (event) => {
      const selectionButton = event.target.closest("[data-cultivation-select='true']");
      if (selectionButton) {
        selectedChildId = Number.parseInt(selectionButton.dataset.childId || "", 10);
        renderEditor();
        return;
      }

      if (event.target.closest("[data-remove-point-index]")) {
        const current = findChild();
        if (!current || current.overlay_shape === "area") {
          return;
        }
        const removeIndex = Number.parseInt(event.target.closest("[data-remove-point-index]").dataset.removePointIndex || "-1", 10);
        current.points.splice(removeIndex, 1);
        renderEditor();
        return;
      }

      if (event.target.closest("button, a, input, textarea, select, label")) {
        return;
      }

      const current = findChild();
      if (!current || current.overlay_shape === "area") {
        return;
      }
      const point = pointFromPointerEvent(event);
      if (!point) {
        return;
      }
      current.points = Array.isArray(current.points) ? current.points : [];
      current.points.push(point);
      renderEditor();
    });

    handles.forEach((handle) => {
      handle.addEventListener("pointerdown", (event) => {
        const current = findChild();
        const handleIndex = Number.parseInt(handle.dataset.cultivationEditorHandle || "-1", 10);
        if (!current || current.overlay_shape !== "area" || handleIndex < 0) {
          return;
        }
        if (typeof handle.setPointerCapture === "function") {
          handle.setPointerCapture(event.pointerId);
        }
        startDrag(event.pointerId, (point) => {
          if (!Array.isArray(current.polygon) || !current.polygon[handleIndex]) {
            return;
          }
          current.polygon[handleIndex] = point;
          renderEditor();
        });
        event.preventDefault();
        event.stopPropagation();
      });
    });

    pointLayer.addEventListener("pointerdown", (event) => {
      const pointButton = event.target.closest("[data-point-index]");
      const current = findChild();
      if (!pointButton || !current || current.overlay_shape === "area") {
        return;
      }
      const pointIndex = Number.parseInt(pointButton.dataset.pointIndex || "-1", 10);
      if (pointIndex < 0) {
        return;
      }
      if (typeof pointButton.setPointerCapture === "function") {
        pointButton.setPointerCapture(event.pointerId);
      }
      startDrag(event.pointerId, (position) => {
        if (!Array.isArray(current.points) || !current.points[pointIndex]) {
          return;
        }
        current.points[pointIndex] = position;
        renderEditor();
      });
      event.preventDefault();
    });

    container.addEventListener("dragstart", (event) => {
      event.preventDefault();
    });

    renderEditor();
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

/**
 * Initialize live filters on the node detail page without full page reloads.
 */
function initNodeDetailFilters() {
  const filtersForm = document.querySelector("[data-node-filters='true']");
  if (!filtersForm || filtersForm.dataset.filtersReady === "true") {
    return;
  }

  const yearSelect = filtersForm.querySelector("[data-node-filter-year='true']");
  const showDeadInput = filtersForm.querySelector("[data-node-filter-dead='true']");
  const displayModeInput = filtersForm.querySelector("[data-node-filter-display='true']");
  const childCards = Array.from(document.querySelectorAll("[data-node-child-card='true']"));
  const childOverlays = Array.from(document.querySelectorAll("[data-node-overlay='true']"));
  const irrigationOverlays = Array.from(document.querySelectorAll("[data-irrigation-zone='true']"));
  const overlayEmpty = document.querySelector("[data-overlay-empty='true']");
  const childrenEmpty = document.querySelector("[data-children-empty='true']");
  const filterProxies = Array.from(document.querySelectorAll("[data-node-filter-proxy]"));

  const matchesChildFilters = (element) => {
    const isDead = element.dataset.isDead === "true";
    const lifeCycle = element.dataset.lifeCycle || "";
    const cultivationYear = element.dataset.cultivationYear || "";
    const showDead = showDeadInput?.checked ?? false;
    const selectedYear = yearSelect?.value || "";

    if (!showDead && isDead) {
      return false;
    }

    if (lifeCycle === "annual" && selectedYear && cultivationYear !== selectedYear) {
      return false;
    }

    return true;
  };

  const updateUrl = () => {
    const url = new URL(window.location.href);
    if (yearSelect?.value) {
      url.searchParams.set("year", yearSelect.value);
    } else {
      url.searchParams.delete("year");
    }

    if (showDeadInput?.checked) {
      url.searchParams.set("show_dead", "1");
    } else {
      url.searchParams.delete("show_dead");
    }

    if ((displayModeInput?.value || "cultivations") !== "cultivations") {
      url.searchParams.set("display", displayModeInput.value);
    } else {
      url.searchParams.delete("display");
    }
    url.searchParams.delete("show_irrigation");

    window.history.replaceState({}, "", url);
  };

  const syncProxyInputs = () => {
    filterProxies.forEach((input) => {
      if (input.dataset.nodeFilterProxy === "year") {
        input.value = yearSelect?.value || "";
      }
      if (input.dataset.nodeFilterProxy === "show_dead") {
        input.value = showDeadInput?.checked ? "1" : "";
      }
      if (input.dataset.nodeFilterProxy === "display") {
        input.value = displayModeInput?.value || "cultivations";
      }
    });
  };

  const applyFilters = () => {
    const displayMode = displayModeInput?.value || "cultivations";
    const showCultivations = displayMode !== "irrigation";
    const showIrrigation = displayMode !== "cultivations";

    childCards.forEach((card) => {
      card.hidden = !showCultivations || !matchesChildFilters(card);
    });

    childOverlays.forEach((overlay) => {
      overlay.hidden = !showCultivations || !matchesChildFilters(overlay);
    });

    irrigationOverlays.forEach((overlay) => {
      overlay.hidden = !showIrrigation;
    });

    if (childrenEmpty) {
      childrenEmpty.hidden = childCards.some((card) => !card.hidden);
    }

    if (overlayEmpty) {
      const visibleOverlayItem = Array.from(document.querySelectorAll("[data-overlay-item='true']")).some(
        (item) => !item.hidden,
      );
      overlayEmpty.hidden = visibleOverlayItem;
    }

    syncProxyInputs();
    updateUrl();
  };

  filtersForm.dataset.filtersReady = "true";
  [yearSelect, showDeadInput, displayModeInput].forEach((input) => {
    input?.addEventListener("change", applyFilters);
  });

  applyFilters();
}

/**
 * Format a timestamp for the chart x-axis.
 *
 * @param {string} isoValue ISO timestamp string.
 * @param {string} rangeKey Selected history range key.
 * @returns {string}
 */
function formatHistoryTimestamp(isoValue, rangeKey) {
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return rangeKey === "7d"
    ? date.toLocaleDateString([], { day: "2-digit", month: "2-digit" })
    : date.toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/**
 * Format a numeric chart label.
 *
 * @param {number} value Numeric value to format.
 * @returns {string}
 */
function formatHistoryNumber(value) {
  if (!Number.isFinite(value)) {
    return "";
  }
  if (Math.abs(value - Math.round(value)) < 1e-9) {
    return String(Math.round(value));
  }
  return value.toFixed(2).replace(/\.?0+$/, "");
}

/**
 * Escape HTML special characters for injected chart labels.
 *
 * @param {string} value Raw string value.
 * @returns {string}
 */
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * Build a chart SVG and metadata from raw Home Assistant history samples.
 *
 * @param {object} payload Chart payload returned by the backend.
 * @param {object} options Rendering options.
 * @param {number} [options.zoomFactor] Horizontal zoom factor for latest samples.
 * @param {number} [options.panOffset] Number of trailing samples to skip after zoom.
 * @param {string} [options.unit] Unit of measurement for the series.
 * @param {string} [options.ariaLabel] Accessible label for the chart.
 * @returns {{metaHtml: string, chartHtml: string, panState: {visibleCount: number, maxPanOffset: number, panOffset: number}}|null}
 */
function buildEntityHistoryChart(payload, options = {}) {
  const samples = Array.isArray(payload?.samples) ? payload.samples : [];
  if (!samples.length) {
    return null;
  }

  const zoomFactor = Math.max(1, Number.parseInt(options.zoomFactor || 1, 10) || 1);
  const total = samples.length;
  const visibleCount = Math.max(2, Math.ceil(total / zoomFactor));
  const maxPanOffset = Math.max(0, total - visibleCount);
  const panOffset = Math.max(0, Math.min(maxPanOffset, Number.parseInt(options.panOffset || 0, 10) || 0));
  const endIndex = total - panOffset;
  const startIndex = Math.max(0, endIndex - visibleCount);
  const visibleSamples = samples.slice(startIndex, endIndex);
  if (visibleSamples.length < 2) {
    return null;
  }

  const width = 640;
  const height = 260;
  const padLeft = 56;
  const padRight = 18;
  const padTop = 16;
  const padBottom = 34;
  const chartWidth = width - padLeft - padRight;
  const chartHeight = height - padTop - padBottom;

  const parsed = visibleSamples
    .map((sample) => ({
      ts: new Date(sample.ts),
      value: Number(sample.value),
    }))
    .filter((sample) => !Number.isNaN(sample.ts.getTime()) && Number.isFinite(sample.value));

  if (parsed.length < 2) {
    return null;
  }

  const minValue = Math.min(...parsed.map((sample) => sample.value));
  const maxValue = Math.max(...parsed.map((sample) => sample.value));
  const paddedMin = minValue === maxValue ? minValue - 1 : minValue - ((maxValue - minValue) * 0.08);
  const paddedMax = minValue === maxValue ? maxValue + 1 : maxValue + ((maxValue - minValue) * 0.08);
  const valueSpan = Math.max(paddedMax - paddedMin, 1);
  const startTime = parsed[0].ts.getTime();
  const endTime = parsed[parsed.length - 1].ts.getTime();
  const timeSpan = Math.max(endTime - startTime, 1);

  const coordinates = parsed.map((sample) => {
    const x = padLeft + (((sample.ts.getTime() - startTime) / timeSpan) * chartWidth);
    const y = padTop + (chartHeight - (((sample.value - paddedMin) / valueSpan) * chartHeight));
    return { x, y, value: sample.value, ts: sample.ts };
  });

  const linePoints = coordinates.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const areaPoints = `${padLeft},${height - padBottom} ${linePoints} ${coordinates[coordinates.length - 1].x.toFixed(2)},${height - padBottom}`;
  const latest = coordinates[coordinates.length - 1];
  const unit = options.unit ? ` ${escapeHtml(options.unit)}` : "";

  const yTicks = [0, 0.5, 1].map((fraction) => {
    const value = paddedMax - (valueSpan * fraction);
    const y = padTop + (chartHeight * fraction);
    return { label: formatHistoryNumber(value), y };
  });

  const xTicks = [0, 0.5, 1].map((fraction) => {
    const index = Math.min(parsed.length - 1, Math.round((parsed.length - 1) * fraction));
    const point = coordinates[index];
    return { label: formatHistoryTimestamp(parsed[index].ts.toISOString(), payload.range_key), x: point.x };
  });

  const metaHtml = `
    <div class="entity-history-meta">
      <span>${escapeHtml(options.valueLabel || "Value")}: ${escapeHtml(formatHistoryNumber(latest.value))}${unit}</span>
      <span>${escapeHtml(options.minLabel || "Min")}: ${escapeHtml(formatHistoryNumber(minValue))}</span>
      <span>${escapeHtml(options.maxLabel || "Max")}: ${escapeHtml(formatHistoryNumber(maxValue))}</span>
    </div>
  `;

  const chartHtml = `
    <svg class="entity-history-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(options.ariaLabel || "History chart")}">
      ${yTicks.map((tick) => `
        <line x1="${padLeft}" y1="${tick.y.toFixed(2)}" x2="${width - padRight}" y2="${tick.y.toFixed(2)}" class="entity-history-grid-line"></line>
        <text x="${padLeft - 8}" y="${(tick.y + 4).toFixed(2)}" text-anchor="end" class="entity-history-tick">${escapeHtml(tick.label)}</text>
      `).join("")}
      <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${height - padBottom}" class="entity-history-axis-line"></line>
      <line x1="${padLeft}" y1="${height - padBottom}" x2="${width - padRight}" y2="${height - padBottom}" class="entity-history-axis-line"></line>
      <polyline class="entity-history-area" points="${areaPoints}"></polyline>
      <polyline class="entity-history-line" points="${linePoints}"></polyline>
      <circle class="entity-history-dot" cx="${latest.x.toFixed(2)}" cy="${latest.y.toFixed(2)}" r="4"></circle>
      ${xTicks.map((tick) => `
        <text x="${tick.x.toFixed(2)}" y="${height - 8}" text-anchor="middle" class="entity-history-tick">${escapeHtml(tick.label)}</text>
      `).join("")}
    </svg>
  `;

  return {
    metaHtml,
    chartHtml,
    panState: {
      visibleCount,
      maxPanOffset,
      panOffset,
    },
  };
}

/**
 * Render one entity history panel from backend payload.
 *
 * @param {HTMLElement} panel Entity history panel element.
 * @param {object|null} payload Chart payload for the entity.
 * @param {number} [zoomFactor] Horizontal zoom factor.
 */
function renderEntityHistoryPanel(panel, payload, zoomFactor = 1) {
  const shell = panel.querySelector(".entity-history-chart-shell");
  let empty = panel.querySelector("[data-ha-chart-empty='true']");
  if (!shell) {
    return;
  }

  if (!empty) {
    empty = document.createElement("p");
    empty.className = "muted";
    empty.dataset.haChartEmpty = "true";
    empty.textContent = panel.dataset.noDataText || "";
    panel.appendChild(empty);
  }

  if (!payload) {
    shell.innerHTML = "";
    shell.hidden = true;
    delete shell.dataset.haChartData;
    if (empty) {
      empty.hidden = false;
    }
    return;
  }

  const built = buildEntityHistoryChart(payload, {
    zoomFactor,
    unit: panel.dataset.entityUnit || "",
    valueLabel: panel.dataset.labelValue,
    minLabel: panel.dataset.labelMin,
    maxLabel: panel.dataset.labelMax,
    ariaLabel: panel.dataset.chartAriaLabel,
  });

  if (!built) {
    shell.innerHTML = "";
    shell.hidden = true;
    if (empty) {
      empty.hidden = false;
    }
    return;
  }

  shell.innerHTML = `${built.metaHtml}${built.chartHtml}`;
  shell.hidden = false;
  shell.dataset.haChartData = JSON.stringify(payload);
  if (empty) {
    empty.hidden = true;
  }
}

/**
 * Initialize interactive Home Assistant charts, live range updates, and map popups.
 */
function initEntityHistoryPanels() {
  const controls = document.querySelector("[data-ha-history-controls='true']");
  const rangeSelect = controls?.querySelector("[data-ha-history-range='true']");
  const modal = document.querySelector("[data-ha-chart-modal]");
  const modalBody = modal?.querySelector("[data-ha-chart-modal-body]");
  const modalTitle = modal?.querySelector("[data-ha-chart-modal-title]");
  const modalSubtitle = modal?.querySelector("[data-ha-chart-modal-subtitle]");
  const modalRangeSelect = modal?.querySelector("[data-ha-chart-modal-range]");
  const panels = Array.from(document.querySelectorAll("[data-ha-chart-panel='true']"));
  if ((!controls && !panels.length) || document.body.dataset.haChartsReady === "true") {
    return;
  }
  document.body.dataset.haChartsReady = "true";

  const modalState = { entityId: null, zoomFactor: 1, panOffset: 0 };

  const updateUrlRange = (rangeValue) => {
    const url = new URL(window.location.href);
    if (rangeValue && rangeValue !== "1d") {
      url.searchParams.set("ha_range", rangeValue);
    } else {
      url.searchParams.delete("ha_range");
    }
    window.history.replaceState({}, "", url);
  };

  const openModalForEntity = (entityId) => {
    if (!modal || !modalBody || !modalTitle || !modalSubtitle) {
      return;
    }
    const panel = panels.find((item) => item.dataset.entityId === entityId);
    const payload = panel?.querySelector(".entity-history-chart-shell")?.dataset.haChartData;
    if (!panel || !payload) {
      return;
    }
    const parsedPayload = JSON.parse(payload);
    const built = buildEntityHistoryChart(parsedPayload, {
      zoomFactor: modalState.zoomFactor,
      panOffset: modalState.panOffset,
      unit: panel.dataset.entityUnit || "",
      valueLabel: panel.dataset.labelValue,
      minLabel: panel.dataset.labelMin,
      maxLabel: panel.dataset.labelMax,
      ariaLabel: panel.dataset.chartAriaLabel,
    });
    modalState.entityId = entityId;
    if (!built) {
      return;
    }
    modalState.panOffset = built.panState.panOffset;
    modalTitle.textContent = panel.dataset.entityLabel || entityId;
    modalSubtitle.textContent = rangeSelect?.selectedOptions?.[0]?.textContent || "";
    if (modalRangeSelect) {
      modalRangeSelect.value = rangeSelect?.value || "1d";
    }
    modalBody.innerHTML = `<div class="entity-history-modal-chart">${built.metaHtml}${built.chartHtml}</div>`;
    const panLeftButton = modal.querySelector("[data-ha-chart-pan-left]");
    const panRightButton = modal.querySelector("[data-ha-chart-pan-right]");
    if (panLeftButton) {
      panLeftButton.disabled = built.panState.panOffset >= built.panState.maxPanOffset || built.panState.maxPanOffset === 0;
    }
    if (panRightButton) {
      panRightButton.disabled = built.panState.panOffset <= 0;
    }
    modal.hidden = false;
    document.body.classList.add("has-modal-open");
  };

  const closeModal = () => {
    if (!modal) {
      return;
    }
    modal.hidden = true;
    document.body.classList.remove("has-modal-open");
    modalState.entityId = null;
    modalState.zoomFactor = 1;
    modalState.panOffset = 0;
  };

  panels.forEach((panel) => {
    const payload = panel.querySelector(".entity-history-chart-shell")?.dataset.haChartData;
    if (payload) {
      renderEntityHistoryPanel(panel, JSON.parse(payload));
    }
  });

  document.querySelectorAll("[data-ha-chart-open='true']").forEach((trigger) => {
    const activate = () => {
      modalState.zoomFactor = 1;
      modalState.panOffset = 0;
      openModalForEntity(trigger.dataset.entityId || "");
    };
    trigger.addEventListener("click", activate);
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
  });

  modal?.querySelectorAll("[data-ha-chart-close]").forEach((button) => {
    button.addEventListener("click", closeModal);
  });
  modal?.querySelector("[data-ha-chart-zoom-in]")?.addEventListener("click", () => {
    modalState.zoomFactor = Math.min(modalState.zoomFactor * 2, 16);
    modalState.panOffset = 0;
    if (modalState.entityId) {
      openModalForEntity(modalState.entityId);
    }
  });
  modal?.querySelector("[data-ha-chart-zoom-out]")?.addEventListener("click", () => {
    modalState.zoomFactor = Math.max(1, Math.floor(modalState.zoomFactor / 2));
    modalState.panOffset = 0;
    if (modalState.entityId) {
      openModalForEntity(modalState.entityId);
    }
  });
  modal?.querySelector("[data-ha-chart-zoom-reset]")?.addEventListener("click", () => {
    modalState.zoomFactor = 1;
    modalState.panOffset = 0;
    if (modalState.entityId) {
      openModalForEntity(modalState.entityId);
    }
  });
  modal?.querySelector("[data-ha-chart-pan-left]")?.addEventListener("click", () => {
    const panel = panels.find((item) => item.dataset.entityId === modalState.entityId);
    const payload = panel?.querySelector(".entity-history-chart-shell")?.dataset.haChartData;
    if (!payload) {
      return;
    }
    const parsedPayload = JSON.parse(payload);
    const total = Array.isArray(parsedPayload.samples) ? parsedPayload.samples.length : 0;
    const visibleCount = Math.max(2, Math.ceil(total / Math.max(1, modalState.zoomFactor)));
    const step = Math.max(1, Math.floor(visibleCount / 2));
    modalState.panOffset += step;
    openModalForEntity(modalState.entityId);
  });
  modal?.querySelector("[data-ha-chart-pan-right]")?.addEventListener("click", () => {
    const panel = panels.find((item) => item.dataset.entityId === modalState.entityId);
    const payload = panel?.querySelector(".entity-history-chart-shell")?.dataset.haChartData;
    if (!payload) {
      return;
    }
    const parsedPayload = JSON.parse(payload);
    const total = Array.isArray(parsedPayload.samples) ? parsedPayload.samples.length : 0;
    const visibleCount = Math.max(2, Math.ceil(total / Math.max(1, modalState.zoomFactor)));
    const step = Math.max(1, Math.floor(visibleCount / 2));
    modalState.panOffset = Math.max(0, modalState.panOffset - step);
    openModalForEntity(modalState.entityId);
  });

  const refreshHistoryRange = async (rangeValue) => {
    const nodeId = controls?.dataset.nodeId;
    if (!nodeId) {
      return;
    }
    try {
      const response = await fetch(`/nodes/${nodeId}/ha-history?range=${encodeURIComponent(rangeValue)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      panels.forEach((panel) => {
        renderEntityHistoryPanel(panel, payload.charts?.[panel.dataset.entityId] || null);
      });
      updateUrlRange(rangeValue);
      if (rangeSelect) {
        rangeSelect.value = rangeValue;
      }
      if (modalRangeSelect) {
        modalRangeSelect.value = rangeValue;
      }
      if (modalState.entityId) {
        modalState.zoomFactor = 1;
        modalState.panOffset = 0;
        openModalForEntity(modalState.entityId);
      }
    } catch (error) {
      // Keep the current charts visible if live refresh fails.
    }
  };

  rangeSelect?.addEventListener("change", async () => {
    refreshHistoryRange(rangeSelect.value);
  });
  modalRangeSelect?.addEventListener("change", () => {
    refreshHistoryRange(modalRangeSelect.value);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.hidden) {
      closeModal();
    }
  });
}

/**
 * Initialize searchable select widgets backed by hidden native select fields.
 */
function initSearchableSelects() {
  document.querySelectorAll("[data-searchable-select]").forEach((container) => {
    if (container.dataset.searchReady === "true") {
      return;
    }

    const input = container.querySelector("[data-searchable-select-input]");
    const select = container.querySelector("[data-searchable-select-native='true']");
    const optionsLayer = container.querySelector("[data-searchable-select-options]");
    if (!input || !select || !optionsLayer) {
      return;
    }

    container.dataset.searchReady = "true";
    const allOptions = Array.from(select.options).map((option, index) => ({
      value: option.value,
      label: option.textContent || "",
      isPlaceholder: index === 0,
    }));

    const applySelection = (value, label) => {
      select.value = value;
      input.value = value && value !== "0" ? label : "";
      optionsLayer.hidden = true;
    };

    const renderOptions = (filterValue = "") => {
      const normalizedFilter = filterValue.trim().toLowerCase();
      const filtered = allOptions.filter((option) => (
        option.isPlaceholder || !normalizedFilter || option.label.toLowerCase().includes(normalizedFilter)
      ));

      optionsLayer.innerHTML = "";
      filtered.forEach((option) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "searchable-select-option";
        button.textContent = option.label;
        button.dataset.searchableSelectValue = option.value;
        if (select.value === option.value) {
          button.classList.add("is-active");
        }
        optionsLayer.appendChild(button);
      });
      optionsLayer.hidden = filtered.length === 0;
    };

    const selectedLabel = select.selectedOptions?.[0]?.textContent || "";
    if (select.value && select.value !== "0" && selectedLabel) {
      input.value = selectedLabel;
    } else {
      input.value = "";
    }
    optionsLayer.hidden = true;

    input.addEventListener("focus", () => {
      renderOptions(input.value);
    });

    input.addEventListener("input", () => {
      renderOptions(input.value);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        optionsLayer.hidden = true;
      }
    });

    optionsLayer.addEventListener("click", (event) => {
      const option = event.target.closest("[data-searchable-select-value]");
      if (!option) {
        return;
      }
      const value = option.dataset.searchableSelectValue || "0";
      applySelection(value, option.textContent || "");
    });

    document.addEventListener("click", (event) => {
      if (!container.contains(event.target)) {
        optionsLayer.hidden = true;
      }
    });
  });
}

/**
 * Initialize the client-side crop and rotation preview for node photo imports.
 */
function initPhotoImportEditor() {
  document.querySelectorAll("[data-photo-import-editor='true']").forEach((form) => {
    if (form.dataset.photoImportReady === "true") {
      return;
    }

    const fileInput = form.querySelector("[data-photo-import-file='true']");
    const stage = form.querySelector("[data-photo-import-stage='true']");
    const stageImage = form.querySelector("[data-photo-import-image='true']");
    const cropBox = form.querySelector("[data-photo-import-crop-box='true']");
    const line = form.querySelector("[data-photo-import-line='true']");
    const previewButton = form.querySelector("[data-photo-import-preview='true']");
    const resetButton = form.querySelector("[data-photo-import-reset='true']");
    const submitButton = form.querySelector("[data-photo-import-submit='true']");
    const previewShell = form.querySelector("[data-photo-import-preview-shell='true']");
    const resultImage = form.querySelector("[data-photo-import-result='true']");
    const statusLabel = form.querySelector("[data-photo-import-status='true']");
    const emptyLabel = form.querySelector("[data-photo-import-empty='true']");
    const resultEmptyLabel = form.querySelector("[data-photo-import-result-empty='true']");
    const processedInput = form.querySelector("input[name$='processed_image_data']");
    if (!fileInput || !stage || !stageImage || !cropBox || !line || !previewButton || !submitButton || !resultImage || !statusLabel || !emptyLabel || !resultEmptyLabel || !processedInput) {
      return;
    }

    form.dataset.photoImportReady = "true";
    const previewReadyText = stage.dataset.previewReadyText || "Preview ready";
    const previewDirtyText = stage.dataset.previewDirtyText || "Preview needs refresh after the latest changes.";
    const state = {
      objectUrl: null,
      imageLoaded: false,
      rect: { x: 12, y: 12, width: 76, height: 70 },
      lineStart: { x: 22, y: 78 },
      lineEnd: { x: 78, y: 78 },
      activeDrag: null,
      dragPointerId: null,
      dragStart: null,
      previewDirty: false,
    };

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

    const setPreviewDirty = () => {
      state.previewDirty = true;
      processedInput.value = "";
      submitButton.disabled = true;
      resultImage.hidden = true;
      resultEmptyLabel.hidden = false;
      if (previewShell) {
        previewShell.hidden = true;
      }
      statusLabel.textContent = previewDirtyText;
    };

    const stagePercentFromEvent = (event) => {
      const bounds = stage.getBoundingClientRect();
      const x = clamp(((event.clientX - bounds.left) / bounds.width) * 100, 0, 100);
      const y = clamp(((event.clientY - bounds.top) / bounds.height) * 100, 0, 100);
      return { x, y };
    };

    const syncReferenceLineToCrop = () => {
      state.lineStart = {
        x: state.rect.x + Math.max(8, state.rect.width * 0.12),
        y: state.rect.y + state.rect.height - Math.max(6, state.rect.height * 0.08),
      };
      state.lineEnd = {
        x: state.rect.x + state.rect.width - Math.max(8, state.rect.width * 0.12),
        y: state.rect.y + state.rect.height - Math.max(6, state.rect.height * 0.08),
      };
    };

    const ensureMinimumRect = () => {
      state.rect.width = clamp(state.rect.width, 6, 100);
      state.rect.height = clamp(state.rect.height, 6, 100);
      state.rect.x = clamp(state.rect.x, 0, 100 - state.rect.width);
      state.rect.y = clamp(state.rect.y, 0, 100 - state.rect.height);
    };

    const clampLinePoint = (point) => ({
      x: clamp(point.x, state.rect.x, state.rect.x + state.rect.width),
      y: clamp(point.y, state.rect.y, state.rect.y + state.rect.height),
    });

    const render = () => {
      if (!state.imageLoaded) {
        cropBox.hidden = true;
        line.hidden = true;
        return;
      }

      ensureMinimumRect();
      state.lineStart = clampLinePoint(state.lineStart);
      state.lineEnd = clampLinePoint(state.lineEnd);

      cropBox.hidden = false;
      cropBox.style.left = `${state.rect.x}%`;
      cropBox.style.top = `${state.rect.y}%`;
      cropBox.style.width = `${state.rect.width}%`;
      cropBox.style.height = `${state.rect.height}%`;

      const bounds = stage.getBoundingClientRect();
      const startX = (state.lineStart.x / 100) * bounds.width;
      const startY = (state.lineStart.y / 100) * bounds.height;
      const endX = (state.lineEnd.x / 100) * bounds.width;
      const endY = (state.lineEnd.y / 100) * bounds.height;
      const dx = endX - startX;
      const dy = endY - startY;
      const length = Math.max(16, Math.hypot(dx, dy));
      const angle = Math.atan2(dy, dx) * (180 / Math.PI);

      line.hidden = false;
      line.style.left = `${startX}px`;
      line.style.top = `${startY}px`;
      line.style.width = `${length}px`;
      line.style.transform = `rotate(${angle}deg)`;
    };

    const resetEditor = () => {
      state.rect = { x: 12, y: 12, width: 76, height: 70 };
      syncReferenceLineToCrop();
      render();
      setPreviewDirty();
    };

    const loadSelectedFile = () => {
      const file = fileInput.files?.[0];
      if (!file) {
        processedInput.value = "";
        submitButton.disabled = false;
        if (previewShell) {
          previewShell.hidden = true;
        }
        statusLabel.textContent = previewDirtyText;
        return;
      }

      if (state.objectUrl) {
        URL.revokeObjectURL(state.objectUrl);
      }
      state.objectUrl = URL.createObjectURL(file);
      stageImage.src = state.objectUrl;
      stageImage.hidden = false;
      emptyLabel.hidden = true;
      stageImage.onload = () => {
        state.imageLoaded = true;
        resetEditor();
      };
    };

    const trimCanvas = (canvas) => {
      const context = canvas.getContext("2d");
      if (!context) {
        return canvas;
    }
    const { width, height } = canvas;
    const data = context.getImageData(0, 0, width, height).data;
    let minX = width;
    let minY = height;
    let maxX = -1;
    let maxY = -1;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const alpha = data[(y * width + x) * 4 + 3];
        if (alpha > 0) {
          minX = Math.min(minX, x);
          minY = Math.min(minY, y);
          maxX = Math.max(maxX, x);
          maxY = Math.max(maxY, y);
        }
      }
    }

    if (maxX < minX || maxY < minY) {
      return canvas;
    }

    const output = document.createElement("canvas");
    output.width = maxX - minX + 1;
    output.height = maxY - minY + 1;
    const outputContext = output.getContext("2d");
    if (!outputContext) {
      return canvas;
    }
      outputContext.drawImage(canvas, minX, minY, output.width, output.height, 0, 0, output.width, output.height);
      return output;
    };

    const cropOpaqueInnerRectangle = (canvas) => {
      const context = canvas.getContext("2d");
      if (!context) {
        return canvas;
      }

      const { width, height } = canvas;
      const data = context.getImageData(0, 0, width, height).data;
      const rowSpans = [];

      for (let y = 0; y < height; y += 1) {
        let minX = width;
        let maxX = -1;
        for (let x = 0; x < width; x += 1) {
          const alpha = data[(y * width + x) * 4 + 3];
          if (alpha > 0) {
            minX = Math.min(minX, x);
            maxX = Math.max(maxX, x);
          }
        }
        if (maxX >= minX) {
          rowSpans.push({ minX, maxX, y });
        }
      }

      if (!rowSpans.length) {
        return canvas;
      }

      const cropLeft = rowSpans.reduce((value, row) => Math.max(value, row.minX), 0);
      const cropRight = rowSpans.reduce((value, row) => Math.min(value, row.maxX), width - 1);
      if (cropRight <= cropLeft) {
        return canvas;
      }

      const columnSpans = [];
      for (let x = cropLeft; x <= cropRight; x += 1) {
        let minY = height;
        let maxY = -1;
        for (let y = 0; y < height; y += 1) {
          const alpha = data[(y * width + x) * 4 + 3];
          if (alpha > 0) {
            minY = Math.min(minY, y);
            maxY = Math.max(maxY, y);
          }
        }
        if (maxY >= minY) {
          columnSpans.push({ minY, maxY, x });
        }
      }

      if (!columnSpans.length) {
        return canvas;
      }

      const cropTop = columnSpans.reduce((value, column) => Math.max(value, column.minY), 0);
      const cropBottom = columnSpans.reduce((value, column) => Math.min(value, column.maxY), height - 1);
      if (cropBottom <= cropTop) {
        return canvas;
      }

      const output = document.createElement("canvas");
      output.width = cropRight - cropLeft + 1;
      output.height = cropBottom - cropTop + 1;
      const outputContext = output.getContext("2d");
      if (!outputContext) {
        return canvas;
      }
      outputContext.drawImage(
        canvas,
        cropLeft,
        cropTop,
        output.width,
        output.height,
        0,
        0,
        output.width,
        output.height,
      );
      return output;
    };

    const scaleCanvasToMaxDimension = (canvas, maxDimension) => {
      if (Math.max(canvas.width, canvas.height) <= maxDimension) {
        return canvas;
      }

      const scale = maxDimension / Math.max(canvas.width, canvas.height);
      const output = document.createElement("canvas");
      output.width = Math.max(1, Math.round(canvas.width * scale));
      output.height = Math.max(1, Math.round(canvas.height * scale));
      const outputContext = output.getContext("2d");
      if (!outputContext) {
        return canvas;
      }
      outputContext.drawImage(canvas, 0, 0, output.width, output.height);
      return output;
    };

    const buildPreview = () => {
      if (!state.imageLoaded || !stageImage.naturalWidth || !stageImage.naturalHeight) {
        return;
      }

      const sx = Math.round((state.rect.x / 100) * stageImage.naturalWidth);
      const sy = Math.round((state.rect.y / 100) * stageImage.naturalHeight);
      const sw = Math.max(1, Math.round((state.rect.width / 100) * stageImage.naturalWidth));
      const sh = Math.max(1, Math.round((state.rect.height / 100) * stageImage.naturalHeight));

      const lineStart = {
        x: (state.lineStart.x / 100) * stageImage.naturalWidth,
        y: (state.lineStart.y / 100) * stageImage.naturalHeight,
      };
      const lineEnd = {
        x: (state.lineEnd.x / 100) * stageImage.naturalWidth,
        y: (state.lineEnd.y / 100) * stageImage.naturalHeight,
      };
      const angle = Math.atan2(lineEnd.y - lineStart.y, lineEnd.x - lineStart.x);

      const imageWidth = stageImage.naturalWidth;
      const imageHeight = stageImage.naturalHeight;
      const rotatedWidth = Math.ceil(
        Math.abs(imageWidth * Math.cos(angle)) + Math.abs(imageHeight * Math.sin(angle)),
      );
      const rotatedHeight = Math.ceil(
        Math.abs(imageWidth * Math.sin(angle)) + Math.abs(imageHeight * Math.cos(angle)),
      );
      const rotatedCanvas = document.createElement("canvas");
      rotatedCanvas.width = rotatedWidth;
      rotatedCanvas.height = rotatedHeight;
      const rotatedContext = rotatedCanvas.getContext("2d");
      if (!rotatedContext) {
        return;
      }

      const imageCenter = { x: imageWidth / 2, y: imageHeight / 2 };
      const rotatedCenter = { x: rotatedWidth / 2, y: rotatedHeight / 2 };
      rotatedContext.translate(rotatedWidth / 2, rotatedHeight / 2);
      rotatedContext.rotate(-angle);
      rotatedContext.drawImage(stageImage, -imageWidth / 2, -imageHeight / 2);

      const rotatePoint = (point) => {
        const translatedX = point.x - imageCenter.x;
        const translatedY = point.y - imageCenter.y;
        const cosAngle = Math.cos(-angle);
        const sinAngle = Math.sin(-angle);
        return {
          x: translatedX * cosAngle - translatedY * sinAngle + rotatedCenter.x,
          y: translatedX * sinAngle + translatedY * cosAngle + rotatedCenter.y,
        };
      };

      const rotatedCropCorners = [
        rotatePoint({ x: sx, y: sy }),
        rotatePoint({ x: sx + sw, y: sy }),
        rotatePoint({ x: sx + sw, y: sy + sh }),
        rotatePoint({ x: sx, y: sy + sh }),
      ];
      const cropLeft = Math.max(0, Math.floor(Math.min(...rotatedCropCorners.map((point) => point.x))));
      const cropTop = Math.max(0, Math.floor(Math.min(...rotatedCropCorners.map((point) => point.y))));
      const cropRight = Math.min(rotatedWidth, Math.ceil(Math.max(...rotatedCropCorners.map((point) => point.x))));
      const cropBottom = Math.min(rotatedHeight, Math.ceil(Math.max(...rotatedCropCorners.map((point) => point.y))));
      const croppedWidth = Math.max(1, cropRight - cropLeft);
      const croppedHeight = Math.max(1, cropBottom - cropTop);

      const croppedCanvas = document.createElement("canvas");
      croppedCanvas.width = croppedWidth;
      croppedCanvas.height = croppedHeight;
      const croppedContext = croppedCanvas.getContext("2d");
      if (!croppedContext) {
        return;
      }
      croppedContext.drawImage(
        rotatedCanvas,
        cropLeft,
        cropTop,
        croppedWidth,
        croppedHeight,
        0,
        0,
        croppedWidth,
        croppedHeight,
      );

      const trimmedCanvas = trimCanvas(croppedCanvas);
      const scaledCanvas = scaleCanvasToMaxDimension(trimmedCanvas, 2400);
      const finalCanvas = document.createElement("canvas");
      finalCanvas.width = scaledCanvas.width;
      finalCanvas.height = scaledCanvas.height;
      const finalContext = finalCanvas.getContext("2d");
      if (!finalContext) {
        return;
      }
      finalContext.fillStyle = "#ffffff";
      finalContext.fillRect(0, 0, finalCanvas.width, finalCanvas.height);
      finalContext.drawImage(scaledCanvas, 0, 0);

      const dataUrl = finalCanvas.toDataURL("image/jpeg", 0.82);
      processedInput.value = dataUrl;
      resultImage.src = dataUrl;
      resultImage.hidden = false;
      resultEmptyLabel.hidden = true;
      if (previewShell) {
        previewShell.hidden = false;
      }
      submitButton.disabled = false;
      state.previewDirty = false;
      statusLabel.textContent = previewReadyText;
    };

    const beginDrag = (event, dragMode) => {
      if (!state.imageLoaded) {
        return;
      }
      state.activeDrag = dragMode;
      state.dragPointerId = event.pointerId;
      state.dragStart = stagePercentFromEvent(event);
      stage.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    };

    stage.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest("[data-photo-import-handle]");
    const lineHandle = event.target.closest("[data-photo-import-line-handle]");

    if (handle) {
      beginDrag(event, `resize-${handle.dataset.photoImportHandle}`);
      return;
    }

    if (lineHandle) {
      beginDrag(event, `line-${lineHandle.dataset.photoImportLineHandle}`);
      return;
    }

    if (event.target === cropBox) {
      beginDrag(event, "move");
      return;
    }

    if (event.target === stage || event.target === stageImage) {
      const point = stagePercentFromEvent(event);
      state.rect = { x: point.x, y: point.y, width: 0.1, height: 0.1 };
      syncReferenceLineToCrop();
      render();
      beginDrag(event, "draw");
      setPreviewDirty();
    }
    });

    window.addEventListener("pointermove", (event) => {
    if (!state.activeDrag || state.dragPointerId !== event.pointerId) {
      return;
    }

    const point = stagePercentFromEvent(event);
    const start = state.dragStart || point;

    if (state.activeDrag === "draw") {
      state.rect = {
        x: Math.min(start.x, point.x),
        y: Math.min(start.y, point.y),
        width: Math.abs(point.x - start.x),
        height: Math.abs(point.y - start.y),
      };
      syncReferenceLineToCrop();
    } else if (state.activeDrag === "move") {
      const deltaX = point.x - start.x;
      const deltaY = point.y - start.y;
      state.rect.x = clamp(state.rect.x + deltaX, 0, 100 - state.rect.width);
      state.rect.y = clamp(state.rect.y + deltaY, 0, 100 - state.rect.height);
      state.lineStart = { x: state.lineStart.x + deltaX, y: state.lineStart.y + deltaY };
      state.lineEnd = { x: state.lineEnd.x + deltaX, y: state.lineEnd.y + deltaY };
      state.dragStart = point;
    } else if (state.activeDrag.startsWith("resize-")) {
      const handleKey = state.activeDrag.replace("resize-", "");
      const right = state.rect.x + state.rect.width;
      const bottom = state.rect.y + state.rect.height;

      if (handleKey.includes("left")) {
        state.rect.x = clamp(point.x, 0, right - 6);
        state.rect.width = right - state.rect.x;
      }
      if (handleKey.includes("right")) {
        state.rect.width = clamp(point.x - state.rect.x, 6, 100 - state.rect.x);
      }
      if (handleKey.includes("top")) {
        state.rect.y = clamp(point.y, 0, bottom - 6);
        state.rect.height = bottom - state.rect.y;
      }
      if (handleKey.includes("bottom")) {
        state.rect.height = clamp(point.y - state.rect.y, 6, 100 - state.rect.y);
      }
      syncReferenceLineToCrop();
    } else if (state.activeDrag === "line-start") {
      state.lineStart = clampLinePoint(point);
    } else if (state.activeDrag === "line-end") {
      state.lineEnd = clampLinePoint(point);
    }

    render();
    setPreviewDirty();
    });

    window.addEventListener("pointerup", (event) => {
    if (state.dragPointerId !== event.pointerId) {
      return;
    }
    state.activeDrag = null;
    state.dragPointerId = null;
    state.dragStart = null;
    });

    resetButton?.addEventListener("click", () => {
      if (!state.imageLoaded) {
        return;
      }
      resetEditor();
    });

    previewButton?.addEventListener("click", () => {
      buildPreview();
    });

    fileInput.addEventListener("change", () => {
      loadSelectedFile();
    });

    if (!fileInput.files?.length && !fileInput.required) {
      submitButton.disabled = false;
    }
  });
}

/**
 * Parse a floating-point value with a fallback.
 *
 * @param {string|number|undefined|null} value Value to parse.
 * @param {*} fallback Value returned when parsing fails.
 * @returns {*}
 */
function parseFloatOrDefault(value, fallback) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * Parse an integer value with a fallback.
 *
 * @param {string|number|undefined|null} value Value to parse.
 * @param {*} fallback Value returned when parsing fails.
 * @returns {*}
 */
function parseIntOrDefault(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * Initialize the Google overview map used on the dashboard.
 *
 * @param {HTMLElement} element DOM element containing map configuration.
 */
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

/**
 * Initialize the Google picker map used to choose area coordinates.
 *
 * @param {HTMLElement} element DOM element containing map configuration.
 */
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

/**
 * Return the Leaflet tile layer configuration for the selected provider.
 *
 * @param {string} provider Leaflet provider key.
 * @returns {{url: string, options: object}}
 */
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

/**
 * Initialize the Leaflet overview map used on the dashboard.
 *
 * @param {HTMLElement} element DOM element containing map configuration.
 */
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

/**
 * Initialize the Leaflet picker map used to choose area coordinates.
 *
 * @param {HTMLElement} element DOM element containing map configuration.
 */
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

/**
 * Initialize every pending Google map on the current page.
 */
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

/**
 * Initialize every pending Leaflet map on the current page.
 */
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

/**
 * Initialize node-type-dependent UI helpers on forms.
 */
window.initPiantalaNodeTypeFields = function initPiantalaNodeTypeFields() {
  syncNodeTypeFields();
  syncMarkerPreview();
  initOverlayEditors();
  initCultivationPositionManagers();
  initPhotoImportEditor();
  initSearchableSelects();
  initNodeDetailFilters();
  initEntityHistoryPanels();
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
initCultivationPositionManagers();
initPhotoImportEditor();
initSearchableSelects();
initNodeDetailFilters();
initEntityHistoryPanels();
