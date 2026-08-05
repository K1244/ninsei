/**
 * Dedicated Playback Client (/player) Script
 * YouTube IFrame API Integration & Automatic Queue State Machine
 */

let ytPlayer = null;
let isPlayerReady = false;
let currentTrack = null;
let progressInterval = null;

// Global callback required by YouTube IFrame API Script
window.onYouTubeIframeAPIReady = function() {
  console.log('[YouTube API] Script loaded. Initializing YT.Player...');
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
};

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
    await fetch('/api/player/event', {
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
    await fetch('/api/player/event', {
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

document.addEventListener('DOMContentLoaded', () => {
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
});

function updatePlayerUI(track) {
  const titleEl = document.getElementById('player-track-title');
  const artistEl = document.getElementById('player-track-artist');
  const backdropEl = document.getElementById('ambient-backdrop');
  const totalTimeEl = document.getElementById('total-time-display');

  if (!track) {
    if (titleEl) titleEl.textContent = 'Queue is Empty';
    if (artistEl) artistEl.textContent = 'Add songs to start playback';
    if (totalTimeEl) totalTimeEl.textContent = '0:00';
    return;
  }

  if (titleEl) titleEl.textContent = track.title;
  if (artistEl) artistEl.textContent = track.artist;
  if (totalTimeEl) totalTimeEl.textContent = formatTime(track.duration_seconds);
  
  if (backdropEl && track.thumbnail_url) {
    backdropEl.style.backgroundImage = `url('${track.thumbnail_url}')`;
  }
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
