/**
 * Admin Dashboard Frontend Script
 * Includes Host Subscription Simulator & Live Event Log
 */

document.addEventListener('DOMContentLoaded', () => {
  const adminQueueList = document.getElementById('admin-queue-list');
  const eventLogContainer = document.getElementById('event-log-container');
  const skipTrackBtn = document.getElementById('skip-track-btn');
  const clearQueueBtn = document.getElementById('clear-queue-btn');
  const statusForm = document.getElementById('subscription-status-form');

  // 1. Listen for WebSocket Queue Updates
  window.JukeboxWS.on('QUEUE_UPDATED', (payload) => {
    renderAdminQueue(payload.queue);
  });

  // 2. Listen for WebSocket Alerts (e.g. Spotify 403 Forbidden alert)
  window.JukeboxWS.on('ALERT_EVENT', (alert) => {
    logAdminEvent(alert);
    if (alert.type === 'error') {
      showToast(alert.message, 'error');
    } else if (alert.type === 'payment') {
      showToast(alert.message, 'success');
    }
  });

  // 3. Skip Track Handler
  if (skipTrackBtn) {
    skipTrackBtn.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/queue/skip', { method: 'POST' });
        if (res.ok) showToast('Track skipped.', 'info');
      } catch (err) {
        showToast('Failed to skip track.', 'error');
      }
    });
  }

  // 4. Clear Queue Handler
  if (clearQueueBtn) {
    clearQueueBtn.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to clear the entire queue?')) return;
      try {
        const res = await fetch('/api/queue/clear', { method: 'DELETE' });
        if (res.ok) showToast('Queue cleared.', 'info');
      } catch (err) {
        showToast('Failed to clear queue.', 'error');
      }
    });
  }

  // 5. Host Subscription & Provider Status Form
  if (statusForm) {
    statusForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const provider = document.getElementById('select-provider').value;
      const tier = document.getElementById('select-tier').value;

      try {
        const res = await fetch('/api/admin/subscription-status', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider, tier })
        });
        const data = await res.json();
        
        if (data.error_code === 403) {
          showToast(`[HTTP 403 Alert] ${data.detail}`, 'error');
        } else {
          showToast(`Provider updated to ${provider.toUpperCase()} (${tier})`, 'success');
        }
      } catch (err) {
        showToast('Failed to update subscription status.', 'error');
      }
    });
  }

  function renderAdminQueue(queue) {
    if (!adminQueueList) return;
    if (!queue || queue.length === 0) {
      adminQueueList.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Queue is empty.</div>';
      return;
    }

    adminQueueList.innerHTML = queue.map((item) => `
      <div class="glass-card" style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;">
        <div style="display: flex; align-items: center; gap: 12px; min-width: 0;">
          <img src="${item.thumbnail_url}" style="width: 40px; height: 40px; border-radius: 6px; object-fit: cover;" alt="art" />
          <div style="min-width: 0;">
            <div style="font-weight: 700; font-size: 0.95rem;">${escapeHtml(item.title)}</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">${escapeHtml(item.artist)} • <span style="color: var(--accent-pink);">${item.status.toUpperCase()}</span></div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          ${item.paid_amount > 0 ? `<span class="badge badge-amber">$${item.paid_amount.toFixed(2)}</span>` : ''}
          <button class="btn btn-danger btn-sm delete-btn" data-queue-id="${item.id}">Remove</button>
        </div>
      </div>
    `).join('');

    adminQueueList.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const qId = btn.dataset.queueId;
        try {
          const res = await fetch(`/api/queue/${qId}`, { method: 'DELETE' });
          if (res.ok) showToast('Item removed.', 'info');
        } catch (err) {
          showToast('Failed to remove item.', 'error');
        }
      });
    });
  }

  function logAdminEvent(alert) {
    if (!eventLogContainer) return;
    const item = document.createElement('div');
    const logClass = alert.type === 'error' ? 'log-error' : alert.type === 'payment' ? 'log-payment' : '';
    item.className = `log-item ${logClass}`;
    
    const timeStr = new Date().toLocaleTimeString();
    item.innerHTML = `
      <div style="font-weight: 700;">${escapeHtml(alert.title || 'System Alert')}</div>
      <div>${escapeHtml(alert.message)}</div>
      <div class="log-time">${timeStr}</div>
    `;

    eventLogContainer.prepend(item);
  }

  function escapeHtml(str) {
    return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
});
