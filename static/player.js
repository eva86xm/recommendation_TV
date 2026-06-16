const root = document.querySelector(".player");
const stage = document.getElementById("stage");
const empty = document.getElementById("empty");
const screenKey = root.dataset.screenKey;

let playlist = [];
let currentIndex = 0;
let slideTimer = null;
let retryTimer = null;
let activeVideo = null;
let playbackToken = 0;

async function loadPlaylist() {
  const response = await fetch(`/api/player/${screenKey}/playlist`, { cache: "no-store" });
  const data = await response.json();
  playlist = data.items || [];
  currentIndex = 0;
  playCurrent();
}

function playCurrent() {
  clearTimeout(slideTimer);
  clearTimeout(retryTimer);
  playbackToken += 1;
  activeVideo = null;
  stage.innerHTML = "";

  if (!playlist.length) {
    empty.classList.add("visible");
    slideTimer = setTimeout(loadPlaylist, 30000);
    return;
  }

  empty.classList.remove("visible");
  const item = playlist[currentIndex % playlist.length];
  const element = item.kind === "video" ? document.createElement("video") : document.createElement("img");

  if (item.kind === "video") {
    element.dataset.finished = "0";
    element.autoplay = true;
    element.muted = true;
    element.defaultMuted = true;
    element.playsInline = true;
    element.controls = false;
    element.preload = "auto";
    element.setAttribute("autoplay", "");
    element.setAttribute("muted", "");
    element.setAttribute("playsinline", "");
    element.setAttribute("webkit-playsinline", "");
    element.setAttribute("preload", "auto");
    element.onended = () => {
      finishVideo(element);
    };
    element.onerror = () => {
      finishVideo(element);
    };
    element.oncanplay = () => startVideo(element, item);
    element.onloadedmetadata = () => startVideo(element, item);
  } else {
    element.onload = () => {
      slideTimer = setTimeout(next, Math.max(1, item.durationSeconds || 10) * 1000);
    };
    element.onerror = next;
  }

  element.src = item.kind === "video" ? withPlaybackToken(item.url) : item.url;
  stage.appendChild(element);

  if (item.kind === "video") {
    activeVideo = element;
    element.load();
    startVideo(element, item);
  }
}

function startVideo(video, item) {
  if (!video || video.dataset.started === "1") {
    return;
  }

  let tries = 0;
  const tryPlay = () => {
    if (video !== activeVideo) {
      return;
    }

    if (video.dataset.started === "1") {
      return;
    }

    tries += 1;
    video.muted = true;
    video.defaultMuted = true;
    if (video.readyState > 0 && video.currentTime > 0.2) {
      video.currentTime = 0;
    }

    const playback = video.play();

    if (playback && typeof playback.then === "function") {
      playback.then(() => {
        video.dataset.started = "1";
      }).catch(() => {
        if (tries < 8) {
          retryTimer = setTimeout(tryPlay, 1500);
        } else {
          slideTimer = setTimeout(next, 3000);
        }
      });
    }
  };

  tryPlay();
}

function resumeActiveVideo() {
  if (activeVideo && activeVideo.paused) {
    activeVideo.muted = true;
    activeVideo.play().catch(() => {});
  }
}

function finishVideo(video) {
  if (!video || video.dataset.finished === "1") {
    return;
  }

  video.dataset.finished = "1";
  clearTimeout(retryTimer);

  try {
    video.pause();
    video.removeAttribute("src");
    video.load();
  } catch (error) {
    // Some TV browsers throw while tearing down media. Moving on is safer.
  }

  if (video === activeVideo) {
    activeVideo = null;
  }

  stage.innerHTML = "";
  slideTimer = setTimeout(next, 1000);
}

function withPlaybackToken(url) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}play=${Date.now()}-${playbackToken}`;
}

function next() {
  clearTimeout(slideTimer);
  clearTimeout(retryTimer);
  currentIndex += 1;
  if (currentIndex >= playlist.length) {
    loadPlaylist();
  } else {
    playCurrent();
  }
}

document.addEventListener("click", resumeActiveVideo);
document.addEventListener("keydown", resumeActiveVideo);

loadPlaylist();
