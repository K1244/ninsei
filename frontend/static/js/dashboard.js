/**
 * Venue Owner Dashboard
 * Auth-gated (redirects to /login on 401), queue moderation, device pairing,
 * simulated subscription, and the host-account/provider simulator.
 */

document.addEventListener('DOMContentLoaded', async () => {
  const adminQueueList = document.getElementById('admin-queue-list');
  const eventLogContainer = document.getElementById('event-log-container');
  const skipTrackBtn = document.getElementById('skip-track-btn');
  const clearQueueBtn = document.getElementById('clear-queue-btn');
  const statusForm = document.getElementById('subscription-status-form');
  const logoutBtn = document.getElementById('logout-btn');
  const claimDeviceForm = document.getElementById('claim-device-form');
  const deviceList = document.getElementById('device-list');
  const playerLinkInput = document.getElementById('player-link-input');
  const copyPlayerLinkBtn = document.getElementById('copy-player-link-btn');
  const regeneratePlayerLinkBtn = document.getElementById('regenerate-player-link-btn');
  const upgradeBtn = document.getElementById('upgrade-subscription-btn');
  const revenueSummaryEl = document.getElementById('revenue-summary');
  const proSettingsForm = document.getElementById('pro-settings-form');
  const proSettingsLocked = document.getElementById('pro-settings-locked');
  const autoplayToggle = document.getElementById('autoplay-toggle');
  const unlockFeeInput = document.getElementById('unlock-fee-input');
  const stylesList = document.getElementById('styles-list');
  const stylesLocked = document.getElementById('styles-locked');
  const addStyleForm = document.getElementById('add-style-form');
  const favoriteGenresForm = document.getElementById('favorite-genres-form');
  const favoriteGenresList = document.getElementById('favorite-genres-list');

  let venue = null;

  // 0. Auth guard -- everything on this page requires an authenticated venue owner.
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) throw new Error('not authenticated');
    venue = await res.json();
  } catch (err) {
    window.location.href = '/login';
    return;
  }

  renderVenueHeader(venue);
  window.JukeboxWS.connect(''); // owner auth comes from the session cookie, no query params needed

  applyProGating(venue);
  await loadRevenue();
  await loadFavoriteGenres();
  if (venue.subscription_tier === 'pro') await loadStyles();

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
        const res = await fetch('/api/dashboard/queue/skip', { method: 'POST' });
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
        const res = await fetch('/api/dashboard/queue/clear', { method: 'DELETE' });
        if (res.ok) showToast('Queue cleared.', 'info');
      } catch (err) {
        showToast('Failed to clear queue.', 'error');
      }
    });
  }

  // 5. Host Subscription & Provider Status Form
  if (statusForm) {
    // Pre-select the venue's current settings rather than always defaulting to youtube/premium.
    const providerSelect = document.getElementById('select-provider');
    const tierSelect = document.getElementById('select-tier');
    if (providerSelect) providerSelect.value = venue.active_provider;
    if (tierSelect) tierSelect.value = venue.host_spotify_tier;

    statusForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const provider = providerSelect.value;
      const tier = tierSelect.value;

      try {
        const res = await fetch('/api/dashboard/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active_provider: provider, host_spotify_tier: tier })
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

  // 6. Logout
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      await fetch('/api/auth/logout', { method: 'POST' });
      window.location.href = '/login';
    });
  }

  // 7. Subscription upgrade (simulated)
  if (upgradeBtn) {
    upgradeBtn.addEventListener('click', async () => {
      const nextTier = venue.subscription_tier === 'pro' ? 'free' : 'pro';
      try {
        const res = await fetch('/api/dashboard/subscription/upgrade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tier: nextTier })
        });
        const data = await res.json();
        if (res.ok) {
          venue.subscription_tier = data.subscription_tier;
          renderVenueHeader(venue);
          applyProGating(venue);
          if (venue.subscription_tier === 'pro') await loadStyles();
          await loadRevenue();
          showToast(`Subscription set to ${data.subscription_tier.toUpperCase()} (simulated).`, 'success');
        } else {
          showToast(data.detail || 'Failed to update subscription.', 'error');
        }
      } catch (err) {
        showToast('Network error updating subscription.', 'error');
      }
    });
  }

  // 8. Device pairing: copyable one-click link + list + manual claim form
  await loadPlayerLink();
  if (copyPlayerLinkBtn) {
    copyPlayerLinkBtn.addEventListener('click', async () => {
      const url = playerLinkInput.value;
      if (!url || url === 'Loading...') return;
      try {
        await navigator.clipboard.writeText(url);
        showToast('Player link copied.', 'success');
      } catch (err) {
        // Clipboard API can be unavailable (older browser, insecure context) --
        // fall back to select-and-let-the-user-copy instead of failing silently.
        playerLinkInput.select();
        showToast('Could not auto-copy -- link is selected, press Ctrl/Cmd+C.', 'info');
      }
    });
  }
  if (regeneratePlayerLinkBtn) {
    regeneratePlayerLinkBtn.addEventListener('click', async () => {
      if (!confirm('Regenerate the player link? The old link will stop working (already-linked devices are unaffected).')) return;
      try {
        const res = await fetch('/api/dashboard/player-link/regenerate', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          playerLinkInput.value = data.url;
          showToast('Player link regenerated.', 'success');
        } else {
          showToast(data.detail || 'Failed to regenerate link.', 'error');
        }
      } catch (err) {
        showToast('Network error regenerating link.', 'error');
      }
    });
  }

  await loadDevices();
  if (claimDeviceForm) {
    claimDeviceForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = document.getElementById('pairing-code-input');
      const code = input.value.trim();
      if (!code) return;

      try {
        const res = await fetch('/api/dashboard/devices/claim', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pairing_code: code })
        });
        const data = await res.json();
        if (res.ok) {
          showToast('Device linked!', 'success');
          input.value = '';
          await loadDevices();
        } else {
          showToast(data.detail || 'Could not link device.', 'error');
        }
      } catch (err) {
        showToast('Network error linking device.', 'error');
      }
    });
  }

  // 9. Pro settings: autoplay toggle + premium style unlock fee
  if (proSettingsForm) {
    proSettingsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (venue.subscription_tier !== 'pro') return; // gated in the UI too, but don't fire the request
      try {
        const res = await fetch('/api/dashboard/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            autoplay_enabled: autoplayToggle.checked,
            premium_style_unlock_fee: parseFloat(unlockFeeInput.value) || 0
          })
        });
        const data = await res.json();
        if (res.ok) {
          venue.autoplay_enabled = autoplayToggle.checked;
          venue.premium_style_unlock_fee = parseFloat(unlockFeeInput.value) || 0;
          showToast('Pro settings saved.', 'success');
        } else {
          showToast(data.detail || 'Failed to save Pro settings.', 'error');
        }
      } catch (err) {
        showToast('Network error saving Pro settings.', 'error');
      }
    });
  }

  // 10. Genre / style rules (Pro-only)
  if (addStyleForm) {
    addStyleForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (venue.subscription_tier !== 'pro') return;
      const nameInput = document.getElementById('style-name-input');
      const ruleSelect = document.getElementById('style-rule-select');
      const name = nameInput.value.trim();
      if (!name) return;

      try {
        const res = await fetch('/api/dashboard/styles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, rule: ruleSelect.value })
        });
        const data = await res.json();
        if (res.ok) {
          showToast(`Style '${data.name}' saved.`, 'success');
          nameInput.value = '';
          await loadStyles();
        } else {
          showToast(data.detail || 'Failed to save style.', 'error');
        }
      } catch (err) {
        showToast('Network error saving style.', 'error');
      }
    });
  }

  // 11. Favorite genres (every plan) -- nudges autoplay's picks, see autoplay_service.py
  if (favoriteGenresForm) {
    favoriteGenresForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const checked = Array.from(favoriteGenresList.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
      try {
        const res = await fetch('/api/dashboard/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ favorite_genres: checked })
        });
        const data = await res.json();
        if (res.ok) {
          venue.favorite_genres = checked;
          showToast('Favorite genres saved.', 'success');
        } else {
          showToast(data.detail || 'Failed to save favorite genres.', 'error');
        }
      } catch (err) {
        showToast('Network error saving favorite genres.', 'error');
      }
    });
  }

  async function loadFavoriteGenres() {
    if (!favoriteGenresList) return;
    try {
      const res = await fetch('/api/dashboard/genre-options');
      if (!res.ok) throw new Error('failed');
      const options = await res.json();
      const selected = new Set(venue.favorite_genres || []);
      favoriteGenresList.innerHTML = options.map(g => `
        <label class="genre-checkbox-item">
          <input type="checkbox" value="${escapeHtml(g.key)}" ${selected.has(g.key) ? 'checked' : ''} />
          ${escapeHtml(g.label)}
        </label>
      `).join('');
    } catch (err) {
      favoriteGenresList.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px; grid-column: 1 / -1;">Failed to load genres.</div>';
    }
  }

  function applyProGating(v) {
    const isPro = v.subscription_tier === 'pro';
    if (proSettingsForm) proSettingsForm.style.display = isPro ? 'flex' : 'none';
    if (proSettingsLocked) proSettingsLocked.style.display = isPro ? 'none' : 'block';
    if (addStyleForm) addStyleForm.style.display = isPro ? 'flex' : 'none';
    if (stylesLocked) stylesLocked.style.display = isPro ? 'none' : 'block';
    if (stylesList) stylesList.style.display = isPro ? 'flex' : 'none';
    if (isPro) {
      if (autoplayToggle) autoplayToggle.checked = !!v.autoplay_enabled;
      if (unlockFeeInput) unlockFeeInput.value = v.premium_style_unlock_fee ?? 2.0;
    }
  }

  async function loadRevenue() {
    if (!revenueSummaryEl) return;
    try {
      const res = await fetch('/api/dashboard/revenue/summary');
      if (!res.ok) throw new Error('failed');
      const r = await res.json();
      revenueSummaryEl.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 0.85rem; color: var(--text-secondary);">Total collected</span>
          <span style="font-weight: 700;">$${r.total_collected.toFixed(2)}</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 0.85rem; color: var(--text-secondary);">Your share (${(r.revenue_share_pct * 100).toFixed(0)}%)</span>
          <span style="font-weight: 700; color: var(--accent-emerald);">$${r.venue_share_total.toFixed(2)}</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 0.85rem; color: var(--text-secondary);">Platform share</span>
          <span style="font-weight: 700; color: var(--text-muted);">$${r.app_share_total.toFixed(2)}</span>
        </div>
        ${r.subscription_tier !== 'pro' ? `<div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">Upgrade to Pro to start keeping a share of every payment.</div>` : ''}
      `;
    } catch (err) {
      revenueSummaryEl.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px;">Failed to load revenue.</div>';
    }
  }

  async function loadStyles() {
    if (!stylesList) return;
    try {
      const res = await fetch('/api/dashboard/styles');
      if (!res.ok) throw new Error('failed');
      const styles = await res.json();
      renderStyles(styles);
    } catch (err) {
      stylesList.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px;">Failed to load styles.</div>';
    }
  }

  function renderStyles(styles) {
    if (!stylesList) return;
    if (!styles || styles.length === 0) {
      stylesList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 12px;">No genre rules yet -- add one below.</div>';
      return;
    }

    const badgeClass = { preferred: 'badge-green', premium_only: 'badge-amber', prohibited: 'badge-rose' };
    const ruleLabel = { preferred: 'Preferred', premium_only: 'Premium-only', prohibited: 'Prohibited' };

    stylesList.innerHTML = styles.map(s => `
      <div class="glass-card" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;">
        <div style="display: flex; align-items: center; gap: 10px; min-width: 0;">
          <span style="font-weight: 700; font-size: 0.9rem;">${escapeHtml(s.name)}</span>
          <span class="badge ${badgeClass[s.rule] || 'badge-purple'}">${ruleLabel[s.rule] || s.rule}</span>
        </div>
        <button class="btn btn-danger btn-sm delete-style-btn" data-style-id="${s.id}">Remove</button>
      </div>
    `).join('');

    stylesList.querySelectorAll('.delete-style-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          const res = await fetch(`/api/dashboard/styles/${btn.dataset.styleId}`, { method: 'DELETE' });
          if (res.ok) {
            showToast('Style removed.', 'info');
            await loadStyles();
          }
        } catch (err) {
          showToast('Failed to remove style.', 'error');
        }
      });
    });
  }

  function renderVenueHeader(v) {
    const nameEl = document.getElementById('dashboard-venue-name');
    const guestLink = document.getElementById('open-guest-page-link');
    const guestUrlEl = document.getElementById('guest-page-url');
    const qrImg = document.getElementById('guest-qr-image');
    const tierLabel = document.getElementById('subscription-tier-label');

    if (nameEl) nameEl.textContent = v.name;
    const guestUrl = `/v/${v.slug}`;
    if (guestLink) guestLink.href = guestUrl;
    if (guestUrlEl) {
      guestUrlEl.href = guestUrl;
      guestUrlEl.textContent = `${window.location.origin}${guestUrl}`;
    }
    if (qrImg) qrImg.src = `/api/v/${v.slug}/qr.svg`;
    if (tierLabel) tierLabel.textContent = v.subscription_tier.toUpperCase();
  }

  async function loadPlayerLink() {
    if (!playerLinkInput) return;
    try {
      const res = await fetch('/api/dashboard/player-link');
      if (!res.ok) throw new Error('failed');
      const data = await res.json();
      // API may return a bare path (no PUBLIC_ORIGIN configured locally) --
      // resolve it against this page's own origin so the copied link is
      // always a complete, pasteable URL either way.
      playerLinkInput.value = new URL(data.url, window.location.origin).href;
    } catch (err) {
      playerLinkInput.value = 'Failed to load link.';
    }
  }

  async function loadDevices() {
    if (!deviceList) return;
    try {
      const res = await fetch('/api/dashboard/devices');
      const devices = await res.json();
      renderDevices(devices);
    } catch (err) {
      deviceList.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px;">Failed to load devices.</div>';
    }
  }

  function renderDevices(devices) {
    if (!deviceList) return;
    if (!devices || devices.length === 0) {
      deviceList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 12px;">No playback devices linked yet.</div>';
      return;
    }

    deviceList.innerHTML = devices.map(d => `
      <div class="glass-card" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;">
        <div style="min-width: 0;">
          <div style="font-weight: 700; font-size: 0.9rem;">${escapeHtml(d.label || `Player #${d.id}`)}</div>
          <div style="font-size: 0.75rem; color: var(--text-muted);">Linked ${d.claimed_at ? new Date(d.claimed_at).toLocaleString() : ''}</div>
        </div>
        <button class="btn btn-danger btn-sm unlink-device-btn" data-device-id="${d.id}">Unlink</button>
      </div>
    `).join('');

    deviceList.querySelectorAll('.unlink-device-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Unlink this playback device?')) return;
        try {
          const res = await fetch(`/api/dashboard/devices/${btn.dataset.deviceId}`, { method: 'DELETE' });
          if (res.ok) {
            showToast('Device unlinked.', 'info');
            await loadDevices();
          }
        } catch (err) {
          showToast('Failed to unlink device.', 'error');
        }
      });
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
          const res = await fetch(`/api/dashboard/queue/${qId}`, { method: 'DELETE' });
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
