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

  // Clubowna community layer
  const communitySettingsForm = document.getElementById('community-settings-form');
  const venueDescriptionInput = document.getElementById('venue-description-input');
  const venueAddressInput = document.getElementById('venue-address-input');
  const sceneThemeSelect = document.getElementById('scene-theme-select');
  const venueModeSelect = document.getElementById('venue-mode-select');
  const modulesChecklist = document.getElementById('modules-checklist');
  const eventsList = document.getElementById('events-list');
  const createEventForm = document.getElementById('create-event-form');
  const eventTypeSelect = document.getElementById('event-type-select');
  const eventAccessModeSelect = document.getElementById('event-access-mode-select');
  const accessRequestsList = document.getElementById('access-requests-list');
  const qrScannerForm = document.getElementById('qr-scanner-form');
  const qrScannerTokenInput = document.getElementById('qr-scanner-token-input');
  const qrScannerResultEl = document.getElementById('qr-scanner-result');
  const qrScannerStartCameraBtn = document.getElementById('qr-scanner-start-camera-btn');
  const qrScannerStopCameraBtn = document.getElementById('qr-scanner-stop-camera-btn');
  const qrScannerCameraWrap = document.getElementById('qr-scanner-camera-wrap');
  const qrScannerVideoEl = document.getElementById('qr-scanner-video');
  const membershipPlansList = document.getElementById('membership-plans-list');
  const createPlanForm = document.getElementById('create-plan-form');
  const productsList = document.getElementById('products-list');
  const createProductForm = document.getElementById('create-product-form');
  const productDescriptionInput = document.getElementById('product-description-input');
  const eventFormSubmitBtn = document.getElementById('event-form-submit-btn');
  const eventFormCancelBtn = document.getElementById('event-form-cancel-btn');
  const planFormSubmitBtn = document.getElementById('plan-form-submit-btn');
  const planFormCancelBtn = document.getElementById('plan-form-cancel-btn');
  const productFormSubmitBtn = document.getElementById('product-form-submit-btn');
  const productFormCancelBtn = document.getElementById('product-form-cancel-btn');

  // Mirrors models.VenueMode -- there's no dedicated options endpoint for
  // this one (unlike modules/event-types/scene-themes) since it's a fixed,
  // small enum embedded directly in the schema rather than a config list.
  const VENUE_MODE_OPTIONS = [
    { key: 'public', label: 'Public -- open to everyone' },
    { key: 'members_only', label: 'Members Only' },
    { key: 'private_event', label: 'Private Event' },
    { key: 'invite_only', label: 'Invite Only' },
    { key: 'observer_allowed', label: 'Observer Allowed (remote-watch only)' },
    { key: 'closed', label: 'Closed' },
  ];
  const MODE_BADGE_CLASS = {
    public: 'badge-green', members_only: 'badge-purple', private_event: 'badge-amber',
    invite_only: 'badge-purple', observer_allowed: 'badge-amber', closed: 'badge-rose',
  };

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

  // Clubowna community layer
  await initCommunitySettings();
  await loadEvents();
  await loadAccessRequests();
  await loadMembershipPlans();
  await loadProducts();
  initQrScanner();

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

  // 12. Community settings: identity, access mode, modules
  if (communitySettingsForm) {
    communitySettingsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const modules = Array.from(modulesChecklist.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
      try {
        const res = await fetch('/api/dashboard/community-settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            description: venueDescriptionInput.value,
            address: venueAddressInput.value,
            scene_theme: sceneThemeSelect.value,
            mode: venueModeSelect.value,
            available_modules: modules,
          })
        });
        const data = await res.json();
        if (res.ok) {
          venue = data;
          showToast('Community settings saved.', 'success');
        } else {
          showToast(data.detail || 'Failed to save community settings.', 'error');
        }
      } catch (err) {
        showToast('Network error saving community settings.', 'error');
      }
    });
  }

  async function initCommunitySettings() {
    if (!communitySettingsForm) return;

    venueModeSelect.innerHTML = VENUE_MODE_OPTIONS.map(m => `<option value="${m.key}">${escapeHtml(m.label)}</option>`).join('');
    eventAccessModeSelect.innerHTML = '<option value="">Use venue default</option>' +
      VENUE_MODE_OPTIONS.map(m => `<option value="${m.key}">${escapeHtml(m.label)}</option>`).join('');

    try {
      const [sceneRes, moduleRes, eventTypeRes] = await Promise.all([
        fetch('/api/dashboard/scene-theme-options'),
        fetch('/api/dashboard/module-options'),
        fetch('/api/dashboard/event-type-options'),
      ]);
      const sceneOptions = sceneRes.ok ? await sceneRes.json() : [];
      const moduleOptions = moduleRes.ok ? await moduleRes.json() : [];
      const eventTypeOptions = eventTypeRes.ok ? await eventTypeRes.json() : [];

      sceneThemeSelect.innerHTML = sceneOptions.map(o => `<option value="${escapeHtml(o.key)}">${escapeHtml(o.label)}</option>`).join('');
      eventTypeSelect.innerHTML = eventTypeOptions.map(o => `<option value="${escapeHtml(o.key)}">${escapeHtml(o.label)}</option>`).join('');

      const enabledModules = new Set(venue.available_modules || []);
      modulesChecklist.innerHTML = moduleOptions.map(o => `
        <label class="genre-checkbox-item">
          <input type="checkbox" value="${escapeHtml(o.key)}" ${enabledModules.has(o.key) ? 'checked' : ''} />
          ${escapeHtml(o.label)}
        </label>
      `).join('');
    } catch (err) {
      modulesChecklist.innerHTML = '<div style="color: var(--accent-rose); grid-column: 1 / -1;">Failed to load module options.</div>';
    }

    venueDescriptionInput.value = venue.description || '';
    venueAddressInput.value = venue.address || '';
    sceneThemeSelect.value = venue.scene_theme || 'pub';
    venueModeSelect.value = venue.mode || 'public';
  }

  // 13. Events -- create-event-form doubles as the edit form: startEditEvent()
  // populates it and flips editingEventId, submit branches POST vs PATCH off
  // that, cancelEventEdit() resets it back to create mode. Same pattern for
  // membership plans (15) and products (16) below.
  let editingEventId = null;

  function resetEventForm() {
    editingEventId = null;
    createEventForm.reset();
    eventAccessModeSelect.value = '';
    document.getElementById('event-request-toggle').checked = true;
    if (eventFormSubmitBtn) eventFormSubmitBtn.textContent = 'Create Event';
    if (eventFormCancelBtn) eventFormCancelBtn.style.display = 'none';
  }

  function startEditEvent(ev) {
    editingEventId = ev.id;
    document.getElementById('event-title-input').value = ev.title;
    eventTypeSelect.value = ev.type;
    eventAccessModeSelect.value = ev.access_mode || '';
    document.getElementById('event-observer-toggle').checked = ev.observer_mode;
    document.getElementById('event-request-toggle').checked = ev.request_access_allowed;
    document.getElementById('event-props-input').value = (ev.scene_props || []).join(', ');
    if (eventFormSubmitBtn) eventFormSubmitBtn.textContent = 'Save Changes';
    if (eventFormCancelBtn) eventFormCancelBtn.style.display = 'block';
    createEventForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  if (eventFormCancelBtn) {
    eventFormCancelBtn.addEventListener('click', resetEventForm);
  }

  if (createEventForm) {
    createEventForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const title = document.getElementById('event-title-input').value.trim();
      if (!title) return;
      const propsRaw = document.getElementById('event-props-input').value.trim();
      const body = {
        title,
        type: eventTypeSelect.value,
        access_mode: eventAccessModeSelect.value || null,
        observer_mode: document.getElementById('event-observer-toggle').checked,
        request_access_allowed: document.getElementById('event-request-toggle').checked,
        scene_props: propsRaw ? propsRaw.split(',').map(s => s.trim()).filter(Boolean) : [],
      };
      const isEdit = editingEventId !== null;
      try {
        const res = await fetch(
          isEdit ? `/api/dashboard/events/${editingEventId}` : '/api/dashboard/events',
          {
            method: isEdit ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          }
        );
        const data = await res.json();
        if (res.ok) {
          showToast(isEdit ? `Event '${data.title}' updated.` : `Event '${data.title}' created.`, 'success');
          resetEventForm();
          await loadEvents();
        } else {
          showToast(data.detail || `Failed to ${isEdit ? 'update' : 'create'} event.`, 'error');
        }
      } catch (err) {
        showToast(`Network error ${isEdit ? 'updating' : 'creating'} event.`, 'error');
      }
    });
  }

  async function loadEvents() {
    if (!eventsList) return;
    try {
      const res = await fetch('/api/dashboard/events');
      if (!res.ok) throw new Error('failed');
      renderEvents(await res.json());
    } catch (err) {
      eventsList.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px;">Failed to load events.</div>';
    }
  }

  function renderEvents(events) {
    if (!eventsList) return;
    if (!events || events.length === 0) {
      eventsList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 12px;">No events yet -- create one below.</div>';
      return;
    }
    eventsList.innerHTML = events.map(ev => `
      <div class="glass-card" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; gap: 8px;">
        <div style="min-width: 0;">
          <div style="font-weight: 700; font-size: 0.9rem;">${escapeHtml(ev.title)}
            ${ev.is_active ? '<span class="badge badge-green" style="margin-left: 6px;">Active</span>' : '<span class="badge badge-purple" style="margin-left: 6px;">Ended</span>'}
          </div>
          <div style="font-size: 0.75rem; color: var(--text-muted);">
            ${escapeHtml(ev.type)}${ev.access_mode ? ` • overrides to ${escapeHtml(ev.access_mode)}` : ''}${ev.observer_mode ? ' • observers on' : ''}
          </div>
        </div>
        <div style="display: flex; gap: 6px; flex-shrink: 0;">
          <button class="btn btn-secondary btn-sm edit-event-btn" data-event-id="${ev.id}">Edit</button>
          <button class="btn btn-danger btn-sm delete-event-btn" data-event-id="${ev.id}">Delete</button>
        </div>
      </div>
    `).join('');

    eventsList.querySelectorAll('.edit-event-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const ev = events.find(e => e.id === Number(btn.dataset.eventId));
        if (ev) startEditEvent(ev);
      });
    });

    eventsList.querySelectorAll('.delete-event-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this event?')) return;
        try {
          const res = await fetch(`/api/dashboard/events/${btn.dataset.eventId}`, { method: 'DELETE' });
          if (res.ok) {
            showToast('Event deleted.', 'info');
            if (editingEventId === Number(btn.dataset.eventId)) resetEventForm();
            await loadEvents();
          }
        } catch (err) {
          showToast('Failed to delete event.', 'error');
        }
      });
    });
  }

  // 14. Access requests
  async function loadAccessRequests() {
    if (!accessRequestsList) return;
    try {
      const res = await fetch('/api/dashboard/access-requests?status=pending');
      if (!res.ok) throw new Error('failed');
      renderAccessRequests(await res.json());
    } catch (err) {
      accessRequestsList.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px;">Failed to load access requests.</div>';
    }
  }

  function renderAccessRequests(requests) {
    if (!accessRequestsList) return;
    if (!requests || requests.length === 0) {
      accessRequestsList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 12px;">No pending requests.</div>';
      return;
    }
    accessRequestsList.innerHTML = requests.map(r => `
      <div class="glass-card" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; gap: 8px;">
        <div style="min-width: 0;">
          <div style="font-weight: 700; font-size: 0.9rem;">${escapeHtml(r.user_display_name || 'Anonymous guest')}</div>
          ${r.note ? `<div style="font-size: 0.8rem; color: var(--text-secondary);">${escapeHtml(r.note)}</div>` : ''}
          <div style="font-size: 0.75rem; color: var(--text-muted);">${new Date(r.created_at).toLocaleString()}</div>
        </div>
        <div style="display: flex; gap: 6px; flex-shrink: 0;">
          <button class="btn btn-primary btn-sm decide-request-btn" data-request-id="${r.id}" data-approve="true">Approve</button>
          <button class="btn btn-danger btn-sm decide-request-btn" data-request-id="${r.id}" data-approve="false">Reject</button>
        </div>
      </div>
    `).join('');

    accessRequestsList.querySelectorAll('.decide-request-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          const res = await fetch(`/api/dashboard/access-requests/${btn.dataset.requestId}/decide`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ approve: btn.dataset.approve === 'true' })
          });
          if (res.ok) {
            showToast(btn.dataset.approve === 'true' ? 'Request approved.' : 'Request rejected.', 'info');
            await loadAccessRequests();
          }
        } catch (err) {
          showToast('Failed to decide request.', 'error');
        }
      });
    });
  }

  // 14b. QR entry scanner (PLAN.md section 8's staff/door half -- guest-facing
  // QR pass display already existed, this is what a phone at the door checks
  // it against). Manual token entry always works; camera auto-scan is a
  // progressive enhancement via the browser's native BarcodeDetector API
  // (supported on most Android browsers, not iOS Safari/older desktop --
  // the "Scan with Camera" button just stays hidden there, manual entry
  // covers every browser).
  let qrScannerStream = null;
  let qrScannerDetectTimer = null;

  function initQrScanner() {
    if (qrScannerForm) {
      qrScannerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const token = qrScannerTokenInput.value.trim();
        if (!token) return;
        await checkQrToken(token);
      });
    }
    if (qrScannerStartCameraBtn && 'BarcodeDetector' in window) {
      qrScannerStartCameraBtn.style.display = 'block';
      qrScannerStartCameraBtn.addEventListener('click', startQrCamera);
    }
    if (qrScannerStopCameraBtn) {
      qrScannerStopCameraBtn.addEventListener('click', stopQrCamera);
    }
  }

  async function checkQrToken(token) {
    if (!qrScannerResultEl) return;
    qrScannerResultEl.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 10px;">Checking...</div>';
    try {
      const res = await fetch('/api/dashboard/qr-scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to check token.');
      renderQrScanResult(data);
    } catch (err) {
      qrScannerResultEl.innerHTML = `<div style="color: var(--accent-rose); text-align: center; padding: 10px;">${escapeHtml(err.message || 'Failed to check token.')}</div>`;
    }
  }

  function renderQrScanResult(data) {
    const meta = {
      allow: { icon: '🟢', badge: 'badge-green', label: 'ALLOW' },
      pending: { icon: '🟡', badge: 'badge-amber', label: 'PENDING' },
      deny: { icon: '🔴', badge: 'badge-rose', label: 'DENY' },
    }[data.result] || { icon: '⚪', badge: 'badge-purple', label: (data.result || 'UNKNOWN').toUpperCase() };

    qrScannerResultEl.innerHTML = `
      <div class="glass-card" style="padding: 14px; text-align: center; margin-top: 4px;">
        <div style="font-size: 1.6rem;">${meta.icon}</div>
        <span class="badge ${meta.badge}" style="margin-top: 4px; display: inline-block;">${meta.label}</span>
        ${data.user_display_name ? `<div style="font-weight: 700; margin-top: 8px;">${escapeHtml(data.user_display_name)}</div>` : ''}
        <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 4px;">${escapeHtml(data.reason)}</div>
      </div>
    `;
  }

  async function startQrCamera() {
    try {
      qrScannerStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      qrScannerVideoEl.srcObject = qrScannerStream;
      await qrScannerVideoEl.play();
      qrScannerCameraWrap.style.display = 'block';
      qrScannerStartCameraBtn.style.display = 'none';

      const detector = new BarcodeDetector({ formats: ['qr_code'] });
      qrScannerDetectTimer = setInterval(async () => {
        try {
          const codes = await detector.detect(qrScannerVideoEl);
          if (codes.length > 0 && codes[0].rawValue) {
            const value = codes[0].rawValue;
            stopQrCamera();
            qrScannerTokenInput.value = value;
            await checkQrToken(value);
          }
        } catch (err) {
          // Transient decode error (frame not ready yet, etc.) -- ignore and
          // let the next tick try again.
        }
      }, 400);
    } catch (err) {
      showToast('Could not access the camera -- use manual entry instead.', 'error');
    }
  }

  function stopQrCamera() {
    if (qrScannerDetectTimer) {
      clearInterval(qrScannerDetectTimer);
      qrScannerDetectTimer = null;
    }
    if (qrScannerStream) {
      qrScannerStream.getTracks().forEach(t => t.stop());
      qrScannerStream = null;
    }
    if (qrScannerCameraWrap) qrScannerCameraWrap.style.display = 'none';
    if (qrScannerStartCameraBtn && 'BarcodeDetector' in window) qrScannerStartCameraBtn.style.display = 'block';
  }

  // 15. Membership plans -- same create-form-doubles-as-edit-form pattern as
  // events above.
  let editingPlanId = null;

  function resetPlanForm() {
    editingPlanId = null;
    createPlanForm.reset();
    if (planFormSubmitBtn) planFormSubmitBtn.textContent = 'Add Membership Plan';
    if (planFormCancelBtn) planFormCancelBtn.style.display = 'none';
  }

  function startEditPlan(p) {
    editingPlanId = p.id;
    document.getElementById('plan-name-input').value = p.name;
    document.getElementById('plan-price-input').value = p.price;
    document.getElementById('plan-interval-select').value = p.interval;
    document.getElementById('plan-perks-input').value = p.perks || '';
    if (planFormSubmitBtn) planFormSubmitBtn.textContent = 'Save Changes';
    if (planFormCancelBtn) planFormCancelBtn.style.display = 'block';
    createPlanForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  if (planFormCancelBtn) {
    planFormCancelBtn.addEventListener('click', resetPlanForm);
  }

  if (createPlanForm) {
    createPlanForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = document.getElementById('plan-name-input').value.trim();
      if (!name) return;
      const body = {
        name,
        price: parseFloat(document.getElementById('plan-price-input').value) || 0,
        interval: document.getElementById('plan-interval-select').value,
        perks: document.getElementById('plan-perks-input').value.trim() || null,
      };
      const isEdit = editingPlanId !== null;
      try {
        const res = await fetch(
          isEdit ? `/api/dashboard/membership-plans/${editingPlanId}` : '/api/dashboard/membership-plans',
          {
            method: isEdit ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          }
        );
        const data = await res.json();
        if (res.ok) {
          showToast(isEdit ? `Plan '${data.name}' updated.` : `Plan '${data.name}' added.`, 'success');
          resetPlanForm();
          await loadMembershipPlans();
        } else {
          showToast(data.detail || `Failed to ${isEdit ? 'update' : 'add'} plan.`, 'error');
        }
      } catch (err) {
        showToast(`Network error ${isEdit ? 'updating' : 'adding'} plan.`, 'error');
      }
    });
  }

  async function loadMembershipPlans() {
    if (!membershipPlansList) return;
    try {
      const res = await fetch('/api/dashboard/membership-plans');
      if (!res.ok) throw new Error('failed');
      renderMembershipPlans(await res.json());
    } catch (err) {
      membershipPlansList.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px;">Failed to load plans.</div>';
    }
  }

  function renderMembershipPlans(plans) {
    if (!membershipPlansList) return;
    if (!plans || plans.length === 0) {
      membershipPlansList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 12px;">No membership plans yet -- add one below.</div>';
      return;
    }
    membershipPlansList.innerHTML = plans.map(p => `
      <div class="glass-card" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; gap: 8px;">
        <div style="min-width: 0;">
          <div style="font-weight: 700; font-size: 0.9rem;">${escapeHtml(p.name)} <span class="badge badge-amber" style="margin-left: 4px;">$${p.price.toFixed(2)}/${escapeHtml(p.interval)}</span></div>
          ${p.perks ? `<div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(p.perks)}</div>` : ''}
        </div>
        <div style="display: flex; gap: 6px; flex-shrink: 0;">
          <button class="btn btn-secondary btn-sm edit-plan-btn" data-plan-id="${p.id}">Edit</button>
          <button class="btn btn-secondary btn-sm toggle-plan-btn" data-plan-id="${p.id}" data-enabled="${p.enabled}">${p.enabled ? 'Disable' : 'Enable'}</button>
          <button class="btn btn-danger btn-sm delete-plan-btn" data-plan-id="${p.id}">Delete</button>
        </div>
      </div>
    `).join('');

    membershipPlansList.querySelectorAll('.edit-plan-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const plan = plans.find(p => p.id === Number(btn.dataset.planId));
        if (plan) startEditPlan(plan);
      });
    });
    membershipPlansList.querySelectorAll('.toggle-plan-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          const res = await fetch(`/api/dashboard/membership-plans/${btn.dataset.planId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: btn.dataset.enabled !== 'true' })
          });
          if (res.ok) await loadMembershipPlans();
        } catch (err) {
          showToast('Failed to update plan.', 'error');
        }
      });
    });
    membershipPlansList.querySelectorAll('.delete-plan-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this membership plan?')) return;
        try {
          const res = await fetch(`/api/dashboard/membership-plans/${btn.dataset.planId}`, { method: 'DELETE' });
          if (res.ok) {
            showToast('Plan deleted.', 'info');
            if (editingPlanId === Number(btn.dataset.planId)) resetPlanForm();
            await loadMembershipPlans();
          }
        } catch (err) {
          showToast('Failed to delete plan.', 'error');
        }
      });
    });
  }

  // 16. Products -- same create-form-doubles-as-edit-form pattern as events/plans above.
  let editingProductId = null;

  function resetProductForm() {
    editingProductId = null;
    createProductForm.reset();
    if (productFormSubmitBtn) productFormSubmitBtn.textContent = 'Add Product';
    if (productFormCancelBtn) productFormCancelBtn.style.display = 'none';
  }

  function startEditProduct(p) {
    editingProductId = p.id;
    document.getElementById('product-name-input').value = p.name;
    document.getElementById('product-price-input').value = p.price;
    document.getElementById('product-billing-select').value = p.billing_type;
    if (productDescriptionInput) productDescriptionInput.value = p.description || '';
    document.getElementById('product-grants-entry-toggle').checked = p.grants_entitlements.includes('venue_entry');
    if (productFormSubmitBtn) productFormSubmitBtn.textContent = 'Save Changes';
    if (productFormCancelBtn) productFormCancelBtn.style.display = 'block';
    createProductForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  if (productFormCancelBtn) {
    productFormCancelBtn.addEventListener('click', resetProductForm);
  }

  if (createProductForm) {
    createProductForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = document.getElementById('product-name-input').value.trim();
      if (!name) return;
      const grantsEntry = document.getElementById('product-grants-entry-toggle').checked;
      const body = {
        name,
        price: parseFloat(document.getElementById('product-price-input').value) || 0,
        billing_type: document.getElementById('product-billing-select').value,
        description: productDescriptionInput ? (productDescriptionInput.value.trim() || null) : null,
        grants_entitlements: grantsEntry ? ['venue_entry'] : [],
      };
      const isEdit = editingProductId !== null;
      try {
        const res = await fetch(
          isEdit ? `/api/dashboard/products/${editingProductId}` : '/api/dashboard/products',
          {
            method: isEdit ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          }
        );
        const data = await res.json();
        if (res.ok) {
          showToast(isEdit ? `Product '${data.name}' updated.` : `Product '${data.name}' added.`, 'success');
          resetProductForm();
          await loadProducts();
        } else {
          showToast(data.detail || `Failed to ${isEdit ? 'update' : 'add'} product.`, 'error');
        }
      } catch (err) {
        showToast(`Network error ${isEdit ? 'updating' : 'adding'} product.`, 'error');
      }
    });
  }

  async function loadProducts() {
    if (!productsList) return;
    try {
      const res = await fetch('/api/dashboard/products');
      if (!res.ok) throw new Error('failed');
      renderProducts(await res.json());
    } catch (err) {
      productsList.innerHTML = '<div style="color: var(--accent-rose); text-align: center; padding: 12px;">Failed to load products.</div>';
    }
  }

  function renderProducts(products) {
    if (!productsList) return;
    if (!products || products.length === 0) {
      productsList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 12px;">No products yet -- add one below.</div>';
      return;
    }
    productsList.innerHTML = products.map(p => `
      <div class="glass-card" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; gap: 8px;">
        <div style="min-width: 0;">
          <div style="font-weight: 700; font-size: 0.9rem;">${escapeHtml(p.name)} <span class="badge badge-amber" style="margin-left: 4px;">$${p.price.toFixed(2)}</span></div>
          <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(p.billing_type)}${p.grants_entitlements.includes('venue_entry') ? ' • grants entry' : ''}</div>
        </div>
        <div style="display: flex; gap: 6px; flex-shrink: 0;">
          <button class="btn btn-secondary btn-sm edit-product-btn" data-product-id="${p.id}">Edit</button>
          <button class="btn btn-secondary btn-sm toggle-product-btn" data-product-id="${p.id}" data-enabled="${p.enabled}">${p.enabled ? 'Disable' : 'Enable'}</button>
          <button class="btn btn-danger btn-sm delete-product-btn" data-product-id="${p.id}">Delete</button>
        </div>
      </div>
    `).join('');

    productsList.querySelectorAll('.edit-product-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const product = products.find(p => p.id === Number(btn.dataset.productId));
        if (product) startEditProduct(product);
      });
    });
    productsList.querySelectorAll('.toggle-product-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          const res = await fetch(`/api/dashboard/products/${btn.dataset.productId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: btn.dataset.enabled !== 'true' })
          });
          if (res.ok) await loadProducts();
        } catch (err) {
          showToast('Failed to update product.', 'error');
        }
      });
    });
    productsList.querySelectorAll('.delete-product-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this product?')) return;
        try {
          const res = await fetch(`/api/dashboard/products/${btn.dataset.productId}`, { method: 'DELETE' });
          if (res.ok) {
            showToast('Product deleted.', 'info');
            if (editingProductId === Number(btn.dataset.productId)) resetProductForm();
            await loadProducts();
          }
        } catch (err) {
          showToast('Failed to delete product.', 'error');
        }
      });
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
