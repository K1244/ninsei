/**
 * Guest Jukebox Request Page (served at /v/{slug} for every registered venue)
 */

document.addEventListener('DOMContentLoaded', async () => {
  // URL is always /v/<slug> -- same static HTML file for every venue, the
  // slug is read client-side and used to scope every API/WS call.
  const slug = window.location.pathname.split('/')[2];

  const appContainer = document.getElementById('app-container');
  const notFoundEl = document.getElementById('venue-not-found');
  const venueNameLabel = document.getElementById('venue-name-label');
  const qrImage = document.getElementById('qr-image');

  const searchInput = document.getElementById('search-input');
  const searchResults = document.getElementById('search-results');
  const queueList = document.getElementById('queue-list');
  const nowPlayingCard = document.getElementById('now-playing-card');
  const paymentModal = document.getElementById('payment-modal');
  const qrModal = document.getElementById('qr-modal');
  const unlockModal = document.getElementById('unlock-modal');
  const genreSelectWrapper = document.getElementById('genre-select-wrapper');
  const genreSelect = document.getElementById('genre-select');

  let activeQueueIdForPayment = null;
  let selectedTierId = null;
  let priorityTiers = [];
  let searchTimeout = null;
  let pendingUnlockPayload = null;

  const apiBase = `/api/v/${encodeURIComponent(slug)}`;

  // Confirm the slug is a real venue before wiring anything else up.
  try {
    const res = await fetch(`${apiBase}/meta`);
    if (!res.ok) throw new Error('not found');
    const venue = await res.json();
    if (venueNameLabel) venueNameLabel.textContent = venue.name;
    if (qrImage) qrImage.src = `${apiBase}/qr.svg`;
  } catch (err) {
    if (appContainer) appContainer.style.display = 'none';
    if (notFoundEl) notFoundEl.style.display = 'block';
    return; // Don't wire up search/queue/WS for a venue that doesn't exist.
  }

  // 1b. Genre/style picker -- empty for Free venues or Pro venues with no
  // styles configured yet, in which case the whole row stays hidden and
  // every request goes up untagged (style: null), same as before this existed.
  try {
    const stylesRes = await fetch(`${apiBase}/styles`);
    const styles = stylesRes.ok ? await stylesRes.json() : [];
    if (styles.length > 0 && genreSelect && genreSelectWrapper) {
      const optionFor = (s) => {
        if (s.rule === 'prohibited') return `<option value="${escapeHtml(s.name)}" disabled>${escapeHtml(s.name)} — not accepted here</option>`;
        if (s.rule === 'premium_only') return `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)} — premium 🔒</option>`;
        return `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`;
      };
      genreSelect.innerHTML = `<option value="">No specific genre</option>` + styles.map(optionFor).join('');
      genreSelectWrapper.style.display = 'block';
    }
  } catch (err) {
    console.error('Failed to load venue styles:', err);
  }

  // 1. Live WebSockets Queue Listener, scoped to this venue
  window.JukeboxWS.on('QUEUE_UPDATED', (data) => {
    renderNowPlaying(data.currently_playing);
    renderQueue(data.queue);
  });
  window.JukeboxWS.connect(`?venue=${encodeURIComponent(slug)}`);

  // 2. Search Handler with Debounce
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const query = e.target.value.trim();
      clearTimeout(searchTimeout);

      if (!query) {
        searchResults.innerHTML = '';
        return;
      }

      searchTimeout = setTimeout(() => performSearch(query), 300);
    });
  }

  async function performSearch(query) {
    searchResults.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--text-muted);">Searching music catalog...</div>';

    try {
      const res = await fetch(`${apiBase}/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error('Search failed');
      const tracks = await res.json();
      renderSearchResults(tracks);
    } catch (err) {
      console.error(err);
      searchResults.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--accent-rose);">Failed to load search results.</div>';
    }
  }

  function renderSearchResults(tracks) {
    if (!tracks || tracks.length === 0) {
      searchResults.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--text-muted);">No songs found.</div>';
      return;
    }

    searchResults.innerHTML = tracks.map(track => `
      <div class="search-item">
        <div class="search-item-info">
          <img src="${track.thumbnail_url}" class="search-item-thumb" alt="art" />
          <div style="min-width: 0;">
            <div style="font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(track.title)}</div>
            <div style="font-size: 0.85rem; color: var(--text-secondary);">${escapeHtml(track.artist)} • ${formatTime(track.duration_seconds)}</div>
          </div>
        </div>
        <button class="btn btn-primary btn-sm add-btn"
          data-song-id="${track.song_id}"
          data-title="${escapeHtml(track.title)}"
          data-artist="${escapeHtml(track.artist)}"
          data-duration="${track.duration_seconds}"
          data-thumb="${track.thumbnail_url}"
          data-provider="${track.provider}">
          + Add
        </button>
      </div>
    `).join('');

    // Attach click listeners to + Add buttons
    searchResults.querySelectorAll('.add-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const payload = {
          song_id: btn.dataset.songId,
          title: btn.dataset.title,
          artist: btn.dataset.artist,
          duration_seconds: parseInt(btn.dataset.duration),
          thumbnail_url: btn.dataset.thumb,
          provider: btn.dataset.provider,
          user_name: "Guest Jukeboxer",
          style: (genreSelect && genreSelect.value) || null
        };
        await addToQueue(payload);
      });
    });
  }

  async function addToQueue(payload) {
    try {
      const res = await fetch(`${apiBase}/queue/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message, 'success');
        searchResults.innerHTML = '';
        if (searchInput) searchInput.value = '';
      } else if (res.status === 402 && data.detail && data.detail.requires_unlock) {
        // Style needs a paid unlock -- stash the track and open the confirm modal
        // instead of failing outright (see style_service.check_style_for_add).
        openUnlockModal(payload, data.detail);
      } else {
        const message = typeof data.detail === 'string' ? data.detail : (data.detail && data.detail.message);
        showToast(message || 'Error adding song.', 'error');
      }
    } catch (err) {
      showToast('Network error adding song.', 'error');
    }
  }

  // 5b. Premium Style Unlock Modal
  function openUnlockModal(payload, detail) {
    pendingUnlockPayload = {
      ...payload,
      style: detail.style,
      payment_method: 'mock_card'
    };
    const msgEl = document.getElementById('unlock-modal-message');
    if (msgEl) msgEl.textContent = detail.message || `Pay $${Number(detail.unlock_fee).toFixed(2)} to add this ${detail.style} track.`;
    if (unlockModal) unlockModal.classList.add('active');
  }

  const submitUnlockBtn = document.getElementById('submit-unlock-btn');
  if (submitUnlockBtn) {
    submitUnlockBtn.addEventListener('click', async () => {
      if (!pendingUnlockPayload) return;

      submitUnlockBtn.disabled = true;
      submitUnlockBtn.textContent = 'Processing Payment...';

      try {
        const res = await fetch(`${apiBase}/queue/add-premium`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(pendingUnlockPayload)
        });
        const data = await res.json();
        if (res.ok) {
          showToast(data.message, 'success');
          if (unlockModal) unlockModal.classList.remove('active');
          searchResults.innerHTML = '';
          if (searchInput) searchInput.value = '';
          pendingUnlockPayload = null;
        } else {
          showToast(data.detail || 'Payment simulation failed.', 'error');
        }
      } catch (err) {
        showToast('Network error processing payment.', 'error');
      } finally {
        submitUnlockBtn.disabled = false;
        submitUnlockBtn.textContent = 'Pay & Add Song 🔓';
      }
    });
  }

  // 3. Render Currently Playing Hero Card
  function renderNowPlaying(track) {
    if (!nowPlayingCard) return;

    if (!track) {
      nowPlayingCard.innerHTML = `
        <div style="text-align: center; padding: 20px; color: var(--text-muted);">
          <div style="font-size: 2rem; margin-bottom: 8px;">🎵</div>
          <div style="font-weight: 700; font-size: 1.1rem; color: var(--text-main);">Jukebox Idle</div>
          <div style="font-size: 0.85rem;">Add a song above to start the party!</div>
        </div>
      `;
      return;
    }

    nowPlayingCard.innerHTML = `
      <div class="now-playing-header">
        <span class="badge badge-purple">NOW PLAYING</span>
        <div class="equalizer-bars">
          <div class="equalizer-bar"></div>
          <div class="equalizer-bar"></div>
          <div class="equalizer-bar"></div>
          <div class="equalizer-bar"></div>
        </div>
      </div>
      <div class="now-playing-body">
        <div class="album-thumb-container">
          <img src="${track.thumbnail_url}" class="album-thumb" alt="now playing" />
        </div>
        <div class="track-details">
          <div class="track-title">${escapeHtml(track.title)}</div>
          <div class="track-artist">${escapeHtml(track.artist)}</div>
        </div>
      </div>
    `;
  }

  // 4. Render Queue List
  function renderQueue(queue) {
    if (!queueList) return;

    const upcoming = queue.filter(item => item.status === 'queued');

    if (upcoming.length === 0) {
      queueList.innerHTML = `
        <div class="glass-card" style="padding: 24px; text-align: center; color: var(--text-muted);">
          No upcoming tracks in queue. Be the first to request one!
        </div>
      `;
      return;
    }

    queueList.innerHTML = upcoming.map((item, index) => {
      const isPriority = item.priority_score > 0;
      return `
        <div class="glass-card queue-card ${isPriority ? 'priority-boosted' : ''}">
          <div style="display: flex; align-items: center; gap: 14px; min-width: 0;">
            <span class="queue-position">#${index + 1}</span>
            <img src="${item.thumbnail_url}" style="width: 44px; height: 44px; border-radius: 8px; object-fit: cover;" alt="thumb" />
            <div style="min-width: 0;">
              <div style="font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(item.title)}</div>
              <div style="font-size: 0.85rem; color: var(--text-secondary);">${escapeHtml(item.artist)}</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
            ${isPriority ? `<span class="badge badge-amber">⚡ ${item.paid_amount > 0 ? '$' + item.paid_amount.toFixed(2) : 'Priority'}</span>` : ''}
            <button class="btn btn-secondary btn-sm boost-btn" data-queue-id="${item.id}" data-title="${escapeHtml(item.title)}">
              🚀 Boost
            </button>
          </div>
        </div>
      `;
    }).join('');

    // Attach listeners to Boost buttons
    queueList.querySelectorAll('.boost-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        openPaymentModal(btn.dataset.queueId, btn.dataset.title);
      });
    });
  }

  // 5. Mock Payment Modal Logic
  async function openPaymentModal(queueId, title) {
    activeQueueIdForPayment = queueId;
    document.getElementById('modal-song-title').textContent = title;

    // Fetch priority tiers
    try {
      const res = await fetch(`${apiBase}/priority-tiers`);
      priorityTiers = await res.json();
      renderPaymentTiers(priorityTiers);
    } catch (err) {
      console.error(err);
    }

    if (paymentModal) paymentModal.classList.add('active');
  }

  function renderPaymentTiers(tiers) {
    const tierContainer = document.getElementById('tier-options-container');
    if (!tierContainer) return;

    tierContainer.innerHTML = tiers.map((t, idx) => `
      <div class="tier-option ${idx === 0 ? 'selected' : ''}" data-tier-id="${t.id}">
        <div>
          <div style="font-weight: 700; font-size: 1.05rem;">${escapeHtml(t.name)}</div>
          <div style="font-size: 0.85rem; color: var(--text-secondary);">${escapeHtml(t.description || '')}</div>
        </div>
        <div class="tier-cost">$${t.cost.toFixed(2)}</div>
      </div>
    `).join('');

    selectedTierId = tiers[0]?.id;

    tierContainer.querySelectorAll('.tier-option').forEach(opt => {
      opt.addEventListener('click', () => {
        tierContainer.querySelectorAll('.tier-option').forEach(el => el.classList.remove('selected'));
        opt.classList.add('selected');
        selectedTierId = parseInt(opt.dataset.tierId);
      });
    });
  }

  // Submit Mock Payment
  const submitPaymentBtn = document.getElementById('submit-payment-btn');
  if (submitPaymentBtn) {
    submitPaymentBtn.addEventListener('click', async () => {
      if (!activeQueueIdForPayment || !selectedTierId) return;

      submitPaymentBtn.disabled = true;
      submitPaymentBtn.textContent = 'Processing Payment...';

      try {
        const res = await fetch(`${apiBase}/payments/simulate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            queue_id: parseInt(activeQueueIdForPayment),
            tier_id: selectedTierId,
            card_name: "Mock Priority User",
            payment_method: "mock_card"
          })
        });

        const data = await res.json();
        if (res.ok) {
          showToast(data.message, 'success');
          if (paymentModal) paymentModal.classList.remove('active');
        } else {
          showToast(data.detail || 'Payment simulation failed.', 'error');
        }
      } catch (err) {
        showToast('Network error processing payment.', 'error');
      } finally {
        submitPaymentBtn.disabled = false;
        submitPaymentBtn.textContent = 'Pay & Bump Queue 🚀';
      }
    });
  }

  // Modal Close Listeners
  document.querySelectorAll('.close-modal-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (paymentModal) paymentModal.classList.remove('active');
      if (qrModal) qrModal.classList.remove('active');
      if (unlockModal) unlockModal.classList.remove('active');
      pendingUnlockPayload = null;
    });
  });

  const showQrBtn = document.getElementById('show-qr-btn');
  if (showQrBtn && qrModal) {
    showQrBtn.addEventListener('click', () => qrModal.classList.add('active'));
  }

  function escapeHtml(str) {
    return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
});
