const mediaSelect = document.getElementById("media-select");
const durationField = document.getElementById("duration-field");

function updateScheduleFields() {
  if (!mediaSelect || !durationField) {
    return;
  }

  const selected = mediaSelect.options[mediaSelect.selectedIndex];
  const isVideo = selected && selected.dataset.kind === "video";
  durationField.classList.toggle("hidden", isVideo);
}

if (mediaSelect) {
  mediaSelect.addEventListener("change", updateScheduleFields);
  updateScheduleFields();
}
