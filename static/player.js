const root = document.querySelector(".player");
const stage = document.getElementById("stage");
const empty = document.getElementById("empty");
const screenKey = root.dataset.screenKey;

let playlist = [];
let currentIndex = 0;
let timer = null;

async function loadPlaylist() {
  const response = await fetch(`/api/player/${screenKey}/playlist`, { cache: "no-store" });
  const data = await response.json();
  playlist = data.items || [];
  currentIndex = 0;
  playCurrent();
}

function playCurrent() {
  clearTimeout(timer);
  stage.innerHTML = "";

  if (!playlist.length) {
    empty.classList.add("visible");
    timer = setTimeout(loadPlaylist, 30000);
    return;
  }

  empty.classList.remove("visible");
  const item = playlist[currentIndex % playlist.length];
  const element = item.kind === "video" ? document.createElement("video") : document.createElement("img");

  if (item.kind === "video") {
    element.autoplay = true;
    element.muted = true;
    element.playsInline = true;
    element.controls = false;
    element.onended = next;
    element.onerror = next;
  } else {
    element.onload = () => {
      timer = setTimeout(next, Math.max(1, item.durationSeconds || 10) * 1000);
    };
    element.onerror = next;
  }

  element.src = item.url;
  stage.appendChild(element);

  if (item.kind === "video") {
    element.play().catch(() => {
      timer = setTimeout(next, Math.max(1, item.durationSeconds || 10) * 1000);
    });
  }
}

function next() {
  currentIndex += 1;
  if (currentIndex >= playlist.length) {
    loadPlaylist();
  } else {
    playCurrent();
  }
}

loadPlaylist();
