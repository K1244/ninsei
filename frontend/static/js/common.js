/**
 * Shared Common Utilities & WebSocket Client for Virtual Jukebox Application
 */

class JukeboxWSClient {
  constructor() {
    this.ws = null;
    this.listeners = {};
    this.reconnectInterval = 3000;
    this.connect();
  }

  connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    console.log(`[JukeboxWS] Connecting to ${wsUrl}...`);
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('[JukeboxWS] Connected successfully.');
      this.emit('connection_change', { connected: true });
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const { type, payload } = data;
        if (type && this.listeners[type]) {
          this.listeners[type].forEach(callback => callback(payload));
        }
      } catch (err) {
        console.error('[JukeboxWS] Error parsing message:', err);
      }
    };

    this.ws.onclose = () => {
      console.warn('[JukeboxWS] Connection closed. Reconnecting in 3s...');
      this.emit('connection_change', { connected: false });
      setTimeout(() => this.connect(), this.reconnectInterval);
    };

    this.ws.onerror = (err) => {
      console.error('[JukeboxWS] WebSocket error:', err);
    };
  }

  on(eventType, callback) {
    if (!this.listeners[eventType]) {
      this.listeners[eventType] = [];
    }
    this.listeners[eventType].push(callback);
  }

  send(type, payload = {}) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, payload }));
    } else {
      console.warn('[JukeboxWS] Cannot send, socket not open.');
    }
  }

  emit(eventType, payload) {
    if (this.listeners[eventType]) {
      this.listeners[eventType].forEach(cb => cb(payload));
    }
  }
}

// Toast notification helper
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  const icon = type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ';
  toast.innerHTML = `
    <span style="font-weight: 800; font-size: 1.1rem;">${icon}</span>
    <span>${message}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Format seconds into MM:SS
function formatTime(seconds) {
  if (!seconds || isNaN(seconds)) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

window.JukeboxWS = new JukeboxWSClient();
