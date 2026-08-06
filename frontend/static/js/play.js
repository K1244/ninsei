/**
 * Playback Device Client (/play)
 * Chromecast-style pairing: this browser registers itself as an unclaimed
 * device, shows a short code, and polls until a venue owner claims it from
 * their dashboard. Once claimed, behaves as the continuous YouTube IFrame API
 * playback client, scoped to that venue via its device_token.
 */

let ytPlayer = null;
let isPlayerReady = false;
let isYtApiReady = false;
let isPaired = false;
let currentTrack = null;
let progressInterval = null;
let deviceToken = null;
let wakeLock = null;

const DEVICE_TOKEN_STORAGE_KEY = 'jukebox_device_token';
const PAIRING_POLL_INTERVAL_MS = 3000;

// --- Screen Wake Lock ---
// This page is a dedicated "leave it running" display (TV/tablet at the
// venue) -- the whole point is continuous playback, so the OS's normal
// screen-off/standby timeout actively breaks it. The Wake Lock API keeps
// the display on for as long as this tab is open and visible; it's
// automatically released by the browser whenever the tab goes into the
// background (tab-switch, app-switch, screen lock) and MUST be re-requested
// once it's visible again, which is what the visibilitychange listener does.
async function requestWakeLock() {
  if (!('wakeLock' in navigator)) {
    console.warn('[WakeLock] Screen Wake Lock API not supported on this browser.');
    showWakeLockFallback();
    return;
  }
  try {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener('release', () => {
      // Fires when the tab is hidden (app-switch/screen-lock) as well as on
      // an explicit release() call -- either way, drop our reference so the
      // visibilitychange listener below knows to re-request it once we're
      // foreground again.
      console.log('[WakeLock] Released.');
      wakeLock = null;
      setWakeLockUI(false);
    });
    setWakeLockUI(true);
    console.log('[WakeLock] Acquired -- display will not sleep while this tab is visible.');
  } catch (err) {
    // Most commonly a permissions/policy rejection (e.g. battery saver mode,
    // or a browser that requires a fresh user gesture). Surface a manual
    // retry button instead of failing silently and leaving the venue
    // wondering why the screen dims mid-set.
    console.warn('[WakeLock] Request failed:', err.message);
    showWakeLockFallback();
  }
}

function showWakeLockFallback() {
  setWakeLockUI(false);
  const retryBtn = document.getElementById('wake-lock-retry-btn');
  if (retryBtn) retryBtn.style.display = 'inline-flex';
}

function setWakeLockUI(active) {
  const badge = document.getElementById('wake-lock-badge');
  const retryBtn = document.getElementById('wake-lock-retry-btn');
  if (badge) badge.style.display = active ? 'flex' : 'none';
  if (active && retryBtn) retryBtn.style.display = 'none';
}

document.addEventListener('visibilitychange', async () => {
  if (document.visibilityState === 'visible' && isPaired && !wakeLock) {
    await requestWakeLock();
  }
});

// Global callback required by YouTube IFrame API Script. May fire before or
// after pairing completes -- only actually create the player once both are true.
window.onYouTubeIframeAPIReady = function() {
  console.log('[YouTube API] Script loaded.');
  isYtApiReady = true;
  if (isPaired) createYtPlayer();
};

function createYtPlayer() {
  if (ytPlayer || !isYtApiReady) return;
  console.log('[YouTube API] Initializing YT.Player...');
  ytPlayer = new YT.Player('youtube-player-iframe', {
    height: '100%',
    width: '100%',
    playerVars: {
      'autoplay': 1,
      'controls': 1,
      'modestbranding': 1,
      'rel': 0,
      'enablejsapi': 1
    },
    events: {
      'onReady': onPlayerReady,
      'onStateChange': onPlayerStateChange,
      'onError': onPlayerError
    }
  });
}

function onPlayerReady(event) {
  console.log('[YouTube Player] Ready!');
  isPlayerReady = true;
  if (currentTrack && currentTrack.song_id) {
    playYouTubeTrack(currentTrack.song_id);
  }
}

function onPlayerStateChange(event) {
  // YT.PlayerState: ENDED = 0, PLAYING = 1, PAUSED = 2, BUFFERING = 3
  if (event.data === YT.PlayerState.ENDED) {
    console.log('[YouTube Player] Track finished playing! Notifying server to advance queue...');
    notifyServerTrackEnded();
  } else if (event.data === YT.PlayerState.PLAYING) {
    startProgressTracking();
  } else if (event.data === YT.PlayerState.PAUSED) {
    stopProgressTracking();
  }
}

function onPlayerError(event) {
  console.error('[YouTube Player] Error code:', event.data);
  notifyServerPlayerError(event.data);
  // Auto advance on error after 3 seconds so player doesn't get stuck
  setTimeout(() => notifyServerTrackEnded(), 3000);
}

function playYouTubeTrack(songId) {
  if (isPlayerReady && ytPlayer && ytPlayer.loadVideoById) {
    ytPlayer.loadVideoById(songId);
  }
}

async function notifyServerTrackEnded() {
  stopProgressTracking();
  try {
    await fetch(`/api/devices/${encodeURIComponent(deviceToken)}/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_type: 'track_ended',
        queue_id: currentTrack ? currentTrack.queue_id : null,
        song_id: currentTrack ? currentTrack.song_id : null
      })
    });
  } catch (err) {
    console.error('[Playback Client] Failed to notify track ended:', err);
  }
}

async function notifyServerPlayerError(errorCode) {
  try {
    await fetch(`/api/devices/${encodeURIComponent(deviceToken)}/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_type: 'player_error',
        song_id: currentTrack ? currentTrack.song_id : null,
        error_message: `YouTube IFrame API Error Code: ${errorCode}`
      })
    });
  } catch (err) {
    console.error('[Playback Client] Failed to notify player error:', err);
  }
}

function startProgressTracking() {
  stopProgressTracking();
  progressInterval = setInterval(() => {
    if (ytPlayer && ytPlayer.getCurrentTime && ytPlayer.getDuration) {
      const currentTime = ytPlayer.getCurrentTime();
      const duration = ytPlayer.getDuration() || (currentTrack ? currentTrack.duration_seconds : 180);

      updateProgressUI(currentTime, duration);

      // Send progress to WS for synced user displays
      window.JukeboxWS.send('PLAYER_STATUS', {
        queue_id: currentTrack ? currentTrack.queue_id : null,
        current_time_seconds: currentTime,
        duration_seconds: duration
      });
    }
  }, 1000);
}

function stopProgressTracking() {
  if (progressInterval) {
    clearInterval(progressInterval);
    progressInterval = null;
  }
}

function updateProgressUI(currentTime, duration) {
  const fill = document.getElementById('progress-fill');
  const currTimeEl = document.getElementById('curr-time-display');
  const totalTimeEl = document.getElementById('total-time-display');

  if (currTimeEl) currTimeEl.textContent = formatTime(currentTime);
  if (totalTimeEl) totalTimeEl.textContent = formatTime(duration);
  if (fill && duration > 0) {
    const percent = Math.min(100, (currentTime / duration) * 100);
    fill.style.width = `${percent}%`;
  }
}

function updatePlayerUI(track) {
  const titleEl = document.getElementById('player-track-title');
  const artistEl = document.getElementById('player-track-artist');
  const backdropEl = document.getElementById('ambient-backdrop');
  const totalTimeEl = document.getElementById('total-time-display');

  if (!track) {
    if (titleEl) titleEl.textContent = 'Queue is Empty';
    if (artistEl) artistEl.textContent = 'Add songs to start playback';
    if (totalTimeEl) totalTimeEl.textContent = '0:00';
    updateMediaSessionMetadata(null);
    return;
  }

  if (titleEl) titleEl.textContent = track.title;
  if (artistEl) artistEl.textContent = track.artist;
  if (totalTimeEl) totalTimeEl.textContent = formatTime(track.duration_seconds);

  if (backdropEl && track.thumbnail_url) {
    backdropEl.style.backgroundImage = `url('${track.thumbnail_url}')`;
  }

  updateMediaSessionMetadata(track);
}

// --- Media Session (lock-screen / OS media controls) ---
// Doesn't replace the Wake Lock above -- this is a separate signal telling
// the OS "there's active media here", which is what puts play/pause/track
// info on the phone's lock screen and notification shade instead of the
// generic browser tab, and on some mobile browsers is also what keeps the
// tab exempt from background-tab throttling while a track is playing.
function setupMediaSessionHandlers() {
  if (!('mediaSession' in navigator)) return;
  navigator.mediaSession.setActionHandler('play', () => ytPlayer && ytPlayer.playVideo && ytPlayer.playVideo());
  navigator.mediaSession.setActionHandler('pause', () => ytPlayer && ytPlayer.pauseVideo && ytPlayer.pauseVideo());
}

function updateMediaSessionMetadata(track) {
  if (!('mediaSession' in navigator)) return;
  if (!track) {
    navigator.mediaSession.metadata = null;
    navigator.mediaSession.playbackState = 'none';
    return;
  }
  navigator.mediaSession.metadata = new MediaMetadata({
    title: track.title,
    artist: track.artist,
    artwork: track.thumbnail_url ? [{ src: track.thumbnail_url, sizes: '512x512', type: 'image/jpeg' }] : []
  });
  navigator.mediaSession.playbackState = 'playing';
}

function renderNextTrackPreview(queue) {
  const nextTrackEl = document.getElementById('next-track-preview');
  if (!nextTrackEl) return;

  const upcoming = (queue || []).filter(item => item.status === 'queued');
  if (upcoming.length === 0) {
    nextTrackEl.innerHTML = '<span style="color: var(--text-muted);">Next: No upcoming songs</span>';
  } else {
    const next = upcoming[0];
    nextTrackEl.innerHTML = `
      <span style="font-weight: 700; color: var(--accent-pink);">NEXT UP:</span>
      <span style="font-weight: 600;">${escapeHtml(next.title)}</span>
      <span style="color: var(--text-secondary);">— ${escapeHtml(next.artist)}</span>
    `;
  }
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// --- Device pairing ---

async function registerDevice() {
  const stored = localStorage.getItem(DEVICE_TOKEN_STORAGE_KEY);
  const res = await fetch('/api/devices/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_token: stored || null })
  });
  const data = await res.json();
  deviceToken = data.device_token;
  localStorage.setItem(DEVICE_TOKEN_STORAGE_KEY, deviceToken);
  return data;
}

function showPairingCode(code) {
  const codeEl = document.getElementById('pairing-code-display');
  if (codeEl) codeEl.textContent = code || '------';
}

async function pollUntilClaimed() {
  try {
    const data = await registerDevice(); // also refreshes the code if it expired
    if (data.claimed) {
      onPaired(data);
      return;
    }
    showPairingCode(data.pairing_code);
  } catch (err) {
    console.error('[Pairing] Poll failed:', err);
  }
  setTimeout(pollUntilClaimed, PAIRING_POLL_INTERVAL_MS);
}

function onPaired(data) {
  isPaired = true;
  const pairingScreen = document.getElementById('pairing-screen');
  const playerStage = document.getElementById('player-stage');
  if (pairingScreen) pairingScreen.style.display = 'none';
  if (playerStage) playerStage.style.display = 'flex';

  const venueLabel = document.getElementById('player-venue-label');
  if (venueLabel && data.venue_name) {
    venueLabel.textContent = `${data.venue_name} — Continuous Playback Client`;
  }

  window.JukeboxWS.connect(`?device_token=${encodeURIComponent(deviceToken)}`);
  createYtPlayer();
  requestWakeLock();
  setupMediaSessionHandlers();
}

document.addEventListener('DOMContentLoaded', async () => {
  const wakeLockRetryBtn = document.getElementById('wake-lock-retry-btn');
  if (wakeLockRetryBtn) {
    wakeLockRetryBtn.addEventListener('click', () => requestWakeLock());
  }

  // Listen for PLAY_TRACK commands from backend WebSocket
  window.JukeboxWS.on('PLAY_TRACK', (payload) => {
    console.log('[Playback Client] Received PLAY_TRACK event:', payload);

    if (!payload.song_id) {
      // Idle / Empty queue state
      currentTrack = null;
      updatePlayerUI(null);
      return;
    }

    currentTrack = payload;
    updatePlayerUI(payload);
    playYouTubeTrack(payload.song_id);
  });

  // Listen for QUEUE_UPDATED to render next track preview
  window.JukeboxWS.on('QUEUE_UPDATED', (payload) => {
    renderNextTrackPreview(payload.queue);
  });

  try {
    const initial = await registerDevice();
    if (initial.claimed) {
      onPaired(initial);
    } else {
      showPairingCode(initial.pairing_code);
      setTimeout(pollUntilClaimed, PAIRING_POLL_INTERVAL_MS);
    }
  } catch (err) {
    console.error('[Pairing] Initial device registration failed:', err);
    const statusEl = document.getElementById('pairing-status');
    if (statusEl) statusEl.textContent = 'Could not reach the server. Retrying...';
    setTimeout(pollUntilClaimed, PAIRING_POLL_INTERVAL_MS);
  }
});
