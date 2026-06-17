const mediaSelect = document.getElementById("media-select");
const durationField = document.getElementById("duration-field");
const mediaPicker = document.querySelector("[data-media-picker]");
const uploadForms = document.querySelectorAll(".upload-form");
const filterControls = document.querySelectorAll("[data-filter-controls]");
const mediaStatusRows = document.querySelectorAll("[data-media-id]");
const STATUS_LABELS = {
  ready: "готово",
  processing: "обрабатывается",
  error: "ошибка",
};

function updateScheduleFields() {
  if (!mediaSelect || !durationField) {
    return;
  }

  const selected = mediaPicker && mediaPicker.querySelector('input[name="media_choice"]:checked');
  const isVideo = selected && selected.dataset.kind === "video";
  durationField.classList.toggle("hidden", isVideo);
}

function syncMediaPicker() {
  if (!mediaPicker || !mediaSelect) {
    return;
  }

  const selected = mediaPicker.querySelector('input[name="media_choice"]:checked');
  const selectedRow = selected && selected.closest("[data-title]");
  const selectedName = mediaPicker.querySelector("[data-selected-media-name]");
  const selectedMeta = mediaPicker.querySelector("[data-selected-media-meta]");

  if (!selected) {
    mediaSelect.value = "";
    if (selectedName) {
      selectedName.textContent = "Файл не выбран";
    }
    if (selectedMeta) {
      selectedMeta.textContent = "Выберите файл из списка";
    }
    updateScheduleFields();
    return;
  }

  mediaSelect.value = selected.value;
  if (selectedName && selectedRow) {
    selectedName.textContent = selectedRow.dataset.title;
  }
  if (selectedMeta && selectedRow) {
    selectedMeta.textContent = selectedRow.dataset.meta;
  }
  updateScheduleFields();
}

if (mediaPicker) {
  mediaPicker.querySelectorAll('input[name="media_choice"]').forEach((input) => {
    input.addEventListener("change", syncMediaPicker);
  });
  syncMediaPicker();
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 МБ";
  }

  const megabytes = bytes / 1024 / 1024;
  if (megabytes >= 1) {
    return `${megabytes.toFixed(1)} МБ`;
  }

  return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
}

function setUploadProgress(form, percent, text) {
  const progress = form.querySelector(".upload-progress");
  const bar = form.querySelector(".upload-progress-bar span");
  const label = form.querySelector(".upload-progress-text");

  if (!progress || !bar || !label) {
    return;
  }

  progress.classList.remove("hidden");
  bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  label.textContent = text;
}

function handleUploadSubmit(event) {
  const form = event.currentTarget;
  const fileInput = form.querySelector('input[type="file"]');
  const file = fileInput && fileInput.files[0];
  const button = form.querySelector('button[type="submit"]');

  if (!file || !window.XMLHttpRequest) {
    return;
  }

  event.preventDefault();
  if (button) {
    button.disabled = true;
  }

  const request = new XMLHttpRequest();
  const data = new FormData(form);

  request.upload.addEventListener("progress", (progressEvent) => {
    if (!progressEvent.lengthComputable) {
      setUploadProgress(form, 5, "Загрузка файла...");
      return;
    }

    const percent = Math.round((progressEvent.loaded / progressEvent.total) * 100);
    const loaded = formatBytes(progressEvent.loaded);
    const total = formatBytes(progressEvent.total);
    setUploadProgress(form, percent, `Загружено ${percent}% (${loaded} из ${total})`);
  });

  request.addEventListener("load", () => {
    if (request.status >= 200 && request.status < 400) {
      setUploadProgress(form, 100, "Файл загружен. Если это видео, оно обрабатывается...");
      window.location.href = request.responseURL || window.location.href;
      return;
    }

    const message = request.status === 413 ? "Файл больше разрешенного лимита" : "Сервер не принял файл";
    setUploadProgress(form, 0, message);
    if (button) {
      button.disabled = false;
    }
  });

  request.addEventListener("error", () => {
    setUploadProgress(form, 0, "Не удалось загрузить файл");
    if (button) {
      button.disabled = false;
    }
  });

  request.open(form.method || "POST", form.action);
  request.send(data);
}

uploadForms.forEach((form) => {
  form.addEventListener("submit", handleUploadSubmit);
});

function setupMediaFilters(controls) {
  const section = controls.closest("section");
  const list = section && section.querySelector('[data-filter-list="media"]');
  const search = controls.querySelector("[data-filter-search]");
  const buttons = controls.querySelectorAll("[data-filter-kind]");

  if (!list || !search || !buttons.length) {
    return;
  }

  const applyFilters = () => {
    const query = search.value.trim().toLowerCase();
    const active = controls.querySelector("[data-filter-kind].active");
    const kind = active ? active.dataset.filterKind : "all";

    list.querySelectorAll("[data-kind]").forEach((row) => {
      const matchesKind = kind === "all" || row.dataset.kind === kind;
      const matchesQuery = !query || row.dataset.name.includes(query);
      row.classList.toggle("hidden", !matchesKind || !matchesQuery);
    });
  };

  search.addEventListener("input", applyFilters);
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      buttons.forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      applyFilters();
    });
  });
}

filterControls.forEach(setupMediaFilters);

function setupMediaPicker() {
  if (!mediaPicker) {
    return;
  }

  const panel = mediaPicker.querySelector("[data-picker-panel]");
  const toggle = mediaPicker.querySelector("[data-toggle-picker]");
  const search = mediaPicker.querySelector("[data-picker-search]");
  const buttons = mediaPicker.querySelectorAll("[data-picker-kind]");
  const rows = mediaPicker.querySelectorAll("[data-kind]");

  if (toggle && panel) {
    toggle.addEventListener("click", () => {
      panel.classList.toggle("hidden");
      toggle.textContent = panel.classList.contains("hidden") ? "Выбрать" : "Скрыть";
      if (!panel.classList.contains("hidden") && search) {
        search.focus();
      }
    });
  }

  if (!search || !buttons.length || !rows.length) {
    return;
  }

  const applyFilters = () => {
    const query = search.value.trim().toLowerCase();
    const active = mediaPicker.querySelector("[data-picker-kind].active");
    const kind = active ? active.dataset.pickerKind : "all";

    rows.forEach((row) => {
      const matchesKind = kind === "all" || row.dataset.kind === kind;
      const matchesQuery = !query || row.dataset.name.includes(query);
      row.classList.toggle("hidden", !matchesKind || !matchesQuery);
    });
  };

  search.addEventListener("input", applyFilters);
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      buttons.forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      applyFilters();
    });
  });

  rows.forEach((row) => {
    const input = row.querySelector('input[name="media_choice"]');
    if (!input) {
      return;
    }

    input.addEventListener("change", () => {
      if (panel && input.checked) {
        panel.classList.add("hidden");
      }
      if (toggle && input.checked) {
        toggle.textContent = "Выбрать";
      }
    });
  });
}

setupMediaPicker();

function updateStatusRow(row, item) {
  const oldStatus = row.dataset.mediaStatus || "ready";
  const nextStatus = item.status || "ready";
  const badge = row.querySelector("[data-media-status-label]");
  const error = row.querySelector("[data-media-error]");

  row.dataset.mediaStatus = nextStatus;
  if (badge) {
    badge.textContent = STATUS_LABELS[nextStatus] || nextStatus;
    badge.classList.remove("status-ready", "status-processing", "status-error");
    badge.classList.add(`status-${nextStatus}`);
  }

  if (error) {
    error.textContent = item.error_message || "";
    error.classList.toggle("hidden", !item.error_message);
  }

  return oldStatus !== nextStatus;
}

async function refreshMediaStatuses() {
  if (!mediaStatusRows.length) {
    return;
  }

  try {
    const response = await fetch("/api/media/status", { cache: "no-store" });
    if (!response.ok) {
      return;
    }

    const data = await response.json();
    const statuses = new Map((data.items || []).map((item) => [String(item.id), item]));
    let becameReady = false;

    mediaStatusRows.forEach((row) => {
      const item = statuses.get(row.dataset.mediaId);
      if (!item) {
        return;
      }

      const oldStatus = row.dataset.mediaStatus || "ready";
      const changed = updateStatusRow(row, item);
      if (changed && oldStatus !== "ready" && item.status === "ready") {
        becameReady = true;
      }
    });

    if (becameReady && mediaPicker) {
      window.location.reload();
    }
  } catch (error) {
    // Статус обновится при следующей проверке или после ручной перезагрузки.
  }
}

if (mediaStatusRows.length) {
  setInterval(refreshMediaStatuses, 5000);
  refreshMediaStatuses();
}
