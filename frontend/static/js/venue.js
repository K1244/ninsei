/**
 * Venue scene (PLAN.md section 3): a pixelart room themed off the venue's
 * scene_theme, walkable via the shared scene-engine.js (see room.js for the
 * same mechanics on the landing room), with hotspots you can walk up to and
 * talk to -- Bartender, DJ, the door (Bouncer, when locked), the Jukebox,
 * and the Hacker NPC (queue-skip side-mechanic, only shows up once you can
 * actually use the jukebox). Every "talk to X" hotspot opens the same
 * generic NPC dialogue modal, driven by the backend's dialogue engine (see
 * dialogue_data.py / dialogue_service.py) -- this file has zero conversation
 * content of its own, just the walk-up-and-open-the-modal plumbing.
 *
 * The CTA panel below the scene is unchanged: every button's visibility is
 * still just "is this flag true" off GET /api/venues/{slug} (see
 * directory_router.py's venue_public_profile / access_service.evaluate_access).
 */

const PATRON_TOKEN_KEY = 'clubowna_patron_token';
const STAGE_W = 1000;
const STAGE_H = 640;
const WALK_BOUNDS = { minX: 60, maxX: 940, minY: 360, maxY: 610 };
const MOVE_SPEED = 260;
const FALLBACK_AVATAR_FILE = 'assets/sprites/avatars/avatars_r0_c0.png';

// Client-side mirror of config.SCENE_THEME_SOURCE_SHEETS' floor choice --
// furniture below is deliberately theme-agnostic (see DECOR/HOTSPOTS), only
// the floor tile actually changes per theme.
const THEME_FLOOR = {
  pub: { sprite: 'assets/sprites/venue/venue_club_tools_r0_c0.png', size: 90 },
  bar: { sprite: 'assets/sprites/venue/venue_club_tools_r0_c0.png', size: 90 },
  club: { sprite: 'assets/sprites/venue/venue_club_tools_r0_c2.png', size: 90 },
  lounge: { sprite: 'assets/sprites/venue/venue_underground_r0_c1.png', size: 90 },
};

// Purely decorative -- plain sprites, no interaction.
const DECOR = [
  { sprite: 'assets/sprites/venue/venue_bar_items_r1_c2.png', x: 340, y: 330, w: 190 }, // booth seating
  { sprite: 'assets/sprites/venue/venue_bar_items_r1_c3.png', x: 60, y: 260, w: 90 },  // plant
  { sprite: 'assets/sprites/venue/venue_bar_items_r1_c4.png', x: 830, y: 190, w: 90 }, // speaker
];

// Walk-up-and-talk hotspots that are always present. `id` maps to
// triggerHotspot() below; most just open the matching NPC's dialogue.
const HOTSPOTS = [
  {
    id: 'bar', label: 'Talk to the Bartender', sprite: 'assets/sprites/venue/venue_bar_items_r0_c0.png',
    x: 60, y: 170, w: 260, walkTo: { x: 190, y: 460 },
  },
  {
    id: 'jukebox', label: 'Use the Jukebox', sprite: 'assets/sprites/venue/venue_bar_items_r0_c2.png',
    x: 350, y: 160, w: 150, walkTo: { x: 420, y: 460 },
  },
  {
    id: 'dj', label: 'Talk to the DJ', sprite: 'assets/sprites/venue/venue_bar_items_r0_c3.png',
    x: 540, y: 175, w: 260, walkTo: { x: 650, y: 460 },
  },
];

const DOOR = {
  id: 'door', label: 'Door', sprite: 'assets/sprites/venue/venue_bar_items_r3_c1.png',
  x: 890, y: 220, w: 110, walkTo: { x: 900, y: 460 },
};
const VIP_ROPE = { sprite: 'assets/sprites/venue/venue_bar_items_r2_c3.png', x: 850, y: 380, w: 150 };
const BOUNCER_AVATAR = 'assets/sprites/avatars/avatars_r4_c0.png';

// The Hacker only shows up once there's an actual queue worth hacking --
// see renderScene's `venue.access.can_use_jukebox` check.
const HACKER = {
  id: 'hacker', label: 'Talk to a shady figure', sprite: 'assets/sprites/avatars/avatars_6_r5_c1.png',
  x: 760, y: 330, w: 70, walkTo: { x: 780, y: 470 },
};

// A handful of stock patron sprites for ambient crowd -- purely decorative,
// not tied to real users, see PLAN.md section 3's "NPC density by event type".
const CROWD_AVATARS = [
  'assets/sprites/avatars/avatars_r0_c0.png',
  'assets/sprites/avatars/avatars_r1_c3.png',
  'assets/sprites/avatars/avatars4_r2_c0.png',
  'assets/sprites/avatars/avatars_3_r0_c0.png',
];

const slug = decodeURIComponent(window.location.pathname.split('/').pop());
let venue = null;
let stageEl, floorEl, playerEl, scene;
let currentDialogueNpc = null;

document.addEventListener('DOMContentLoaded', async () => {
  stageEl = document.getElementById('venue-stage');
  floorEl = document.getElementById('venue-floor');
  playerEl = document.createElement('div');
  playerEl.className = 'room-player';
  playerEl.innerHTML = `<img alt="Your character" />`;

  scene = SceneEngine.createWalkableScene({
    stageEl, playerEl, bounds: WALK_BOUNDS, worldW: STAGE_W, speed: MOVE_SPEED,
  });
  scene.player.x = 500;
  scene.player.y = 580;
  scene.player.avatarFile = FALLBACK_AVATAR_FILE;

  SceneEngine.fitStageToViewport(stageEl, STAGE_W, STAGE_H);
  window.addEventListener('resize', () => SceneEngine.fitStageToViewport(stageEl, STAGE_W, STAGE_H));

  await ensurePatronToken();
  await loadVenue();

  scene.bindMovementInput();
  scene.attachClickToMove('.room-hotspot');
  scene.start();
  bindModalCloseButtons();
});

async function ensurePatronToken() {
  if (localStorage.getItem(PATRON_TOKEN_KEY)) return;
  try {
    const res = await fetch('/api/users/identify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: null }),
    });
    if (res.ok) {
      const user = await res.json();
      localStorage.setItem(PATRON_TOKEN_KEY, user.token);
      if (user.avatar) scene.player.avatarFile = `assets/sprites/avatars/${user.avatar}.png`;
    }
  } catch (err) {
    // Fine -- most reads work anonymously too, see access_service.py.
  }
}

function patronHeaders(extra = {}) {
  const token = localStorage.getItem(PATRON_TOKEN_KEY);
  return { 'Content-Type': 'application/json', 'X-User-Token': token || '', ...extra };
}

async function loadVenue() {
  try {
    const res = await fetch(`/api/venues/${encodeURIComponent(slug)}`, { headers: patronHeaders() });
    if (res.status === 404) {
      document.getElementById('venue-panel').innerHTML =
        '<div class="glass-card venue-panel-section" style="text-align:center; color: var(--text-muted);">This venue doesn\'t exist (or closed for the night).</div>';
      return;
    }
    if (!res.ok) throw new Error('failed');
    venue = await res.json();
    document.getElementById('venue-title').textContent = `🏛️ ${venue.name}`;
    document.title = `Clubowna -- ${venue.name}`;
    renderScene();
    renderPanel();
  } catch (err) {
    document.getElementById('venue-panel').innerHTML =
      '<div class="glass-card venue-panel-section" style="text-align:center; color: var(--accent-rose);">Failed to load this venue.</div>';
  }
}

// --- Scene rendering -----------------------------------------------------

function renderScene() {
  const floor = THEME_FLOOR[venue.scene_theme] || THEME_FLOOR.pub;
  floorEl.style.backgroundImage = `url('/static/${floor.sprite}')`;
  floorEl.style.backgroundSize = `${floor.size}px ${floor.size}px`;

  DECOR.forEach(d => stageEl.appendChild(makeSprite(d)));
  HOTSPOTS.forEach(h => stageEl.appendChild(makeHotspotButton(h)));

  const locked = !venue.access.can_enter_venue;
  stageEl.appendChild(makeHotspotButton(DOOR));
  if (locked) {
    stageEl.appendChild(makeSprite(VIP_ROPE));
    stageEl.appendChild(makeCrowdFigure(BOUNCER_AVATAR, DOOR.x - 10, 480));
  }

  if (venue.access.can_use_jukebox) {
    stageEl.appendChild(makeHotspotButton(HACKER));
  }

  const crowdCount = venue.active_event ? 3 : 2;
  const seed = hashString(venue.slug);
  for (let i = 0; i < crowdCount; i++) {
    const avatar = CROWD_AVATARS[(seed + i) % CROWD_AVATARS.length];
    const x = 150 + ((seed * (i + 3)) % 650);
    const y = 460 + ((seed * (i + 7)) % 100);
    stageEl.appendChild(makeCrowdFigure(avatar, x, y));
  }

  if (venue.active_event && venue.active_event.scene_props.length) {
    venue.active_event.scene_props.forEach((propKey, i) => {
      const sprite = PROP_SPRITES[propKey];
      if (!sprite) return;
      stageEl.appendChild(makeSprite({ sprite, x: 120 + i * 140, y: 40, w: 110 }));
    });
  }

  stageEl.appendChild(playerEl);
  scene.renderPlayer();
}

// Mirrors config.SCENE_PROP_SPRITES -- only the keys seed_demo.py's example
// events actually use are wired here; unmapped keys are silently skipped
// (see renderScene above) rather than showing a broken image.
const PROP_SPRITES = {
  balloons: 'assets/sprites/props/items_r0_c0.png',
  cake: 'assets/sprites/props/items_r1_c1.png',
  wedding_decor: 'assets/sprites/props/items_r0_c3.png',
  flowers: 'assets/sprites/props/items_r0_c2.png',
};

function makeSprite({ sprite, x, y, w }) {
  const img = document.createElement('img');
  img.src = `/static/${sprite}`;
  img.className = 'room-sprite';
  img.alt = '';
  img.style.left = `${x}px`;
  img.style.top = `${y}px`;
  img.style.width = `${w}px`;
  return img;
}

// A walk-up-and-interact hotspot -- same `.room-hotspot` button room.js's
// bed/computer/poster use, so it gets the same hover glow/label for free.
function makeHotspotButton(h) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'room-hotspot';
  btn.style.left = `${h.x}px`;
  btn.style.top = `${h.y}px`;
  btn.style.width = `${h.w}px`;
  btn.setAttribute('aria-label', h.label);
  btn.innerHTML = `
    <span class="room-hotspot-label">${escapeHtml(h.label)}</span>
    <img src="/static/${h.sprite}" alt="" />
  `;
  btn.addEventListener('click', () => scene.walkTo(h.walkTo, () => triggerHotspot(h.id)));
  return btn;
}

function makeCrowdFigure(sprite, x, y) {
  const div = document.createElement('div');
  div.className = 'venue-crowd-figure';
  div.style.left = `${x}px`;
  div.style.top = `${y}px`;
  div.innerHTML = `<img src="/static/${sprite}" alt="" />`;
  return div;
}

function hashString(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h;
}

// --- Hotspot actions -------------------------------------------------

function triggerHotspot(id) {
  switch (id) {
    case 'bar':
      openDialogue('bartender');
      break;
    case 'dj':
      openDialogue('dj');
      break;
    case 'hacker':
      openDialogue('hacker');
      break;
    case 'jukebox':
      if (venue.access.can_use_jukebox) {
        window.location.href = `/v/${encodeURIComponent(venue.slug)}`;
      } else {
        showToast(venue.access.reason, 'info');
      }
      break;
    case 'door':
      if (!venue.access.can_enter_venue) {
        openDialogue('bouncer');
      } else {
        showToast('Feel free to step outside any time.', 'info');
      }
      break;
  }
}

// --- NPC dialogue modal ------------------------------------------------
// Generic renderer for whatever node the backend's dialogue engine returns
// (see dialogue_service.py) -- this file has no conversation content of its
// own, just fetch -> render -> post the chosen choice back -> re-render.

async function openDialogue(npcId) {
  currentDialogueNpc = npcId;
  openModal('dialogue-modal');
  renderDialogueLoading();
  try {
    const res = await fetch(`/api/v/${encodeURIComponent(slug)}/npcs/${encodeURIComponent(npcId)}/dialogue`, {
      headers: patronHeaders(),
    });
    if (!res.ok) throw new Error('failed');
    renderDialogueNode(await res.json());
  } catch (err) {
    renderDialogueError("They're not around right now.");
  }
}

function renderDialogueLoading() {
  document.getElementById('dialogue-body').innerHTML = '<p class="dialogue-line" style="color: var(--text-muted);">...</p>';
}

function renderDialogueError(message) {
  document.getElementById('dialogue-body').innerHTML = `<p class="dialogue-line" style="color: var(--accent-rose);">${escapeHtml(message)}</p>`;
}

function renderDialogueNode(node) {
  const body = document.getElementById('dialogue-body');
  body.innerHTML = `
    <div class="dialogue-header">
      <img class="dialogue-avatar" src="/static/${escapeHtml(node.avatar)}" alt="" />
      <div class="dialogue-speaker">${escapeHtml(node.speaker)}</div>
    </div>
    <p class="dialogue-line">${escapeHtml(node.line)}</p>
    <div class="dialogue-choices">
      ${node.choices.map((c, i) => `<button type="button" class="btn btn-secondary btn-sm dialogue-choice-btn" data-index="${i}">${escapeHtml(c.label)}</button>`).join('')}
    </div>
  `;
  body.querySelectorAll('.dialogue-choice-btn').forEach(btn => {
    btn.addEventListener('click', () => handleDialogueChoice(node.choices[Number(btn.dataset.index)]));
  });
}

async function handleDialogueChoice(choice) {
  if (choice.end || !choice.next) {
    closeModal('dialogue-modal');
    return;
  }
  renderDialogueLoading();
  try {
    const res = await fetch(`/api/v/${encodeURIComponent(slug)}/npcs/${encodeURIComponent(currentDialogueNpc)}/dialogue/advance`, {
      method: 'POST',
      headers: patronHeaders(),
      body: JSON.stringify({ next: choice.next, context: choice.context || {} }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(errorDetail(data, 'Something went wrong.'));
    renderDialogueNode(data);
    // The Hacker's favor/payment can move the venue's live queue -- no need
    // to reload the whole scene for it, the dialogue's own success line
    // already says so.
  } catch (err) {
    renderDialogueError(err.message || 'Something went wrong.');
  }
}

// --- CTA panel -------------------------------------------------------

function renderPanel() {
  const panel = document.getElementById('venue-panel');
  const a = venue.access;
  const sections = [];

  sections.push(`
    <div class="glass-card venue-panel-section">
      <div class="venue-panel-title" style="font-weight: 700;">${escapeHtml(venue.name)}</div>
      ${venue.description ? `<p style="color: var(--text-secondary); font-size: 0.88rem; margin: 4px 0 10px;">${escapeHtml(venue.description)}</p>` : ''}
      <div class="venue-reason">${escapeHtml(a.reason)}</div>
      <div class="venue-cta-row">
        ${a.can_use_jukebox ? `<a href="/v/${encodeURIComponent(venue.slug)}" class="btn btn-primary">🎵 Enter &amp; Use Jukebox</a>` : ''}
        ${(!a.can_enter_venue && a.can_observe_event) ? `<button class="btn btn-secondary" id="observe-btn">👀 Watch as Observer</button>` : ''}
        ${a.can_show_qr ? `<button class="btn btn-secondary" id="qr-btn">📱 Show My QR Pass</button>` : ''}
      </div>
      <div id="observe-panel"></div>
      <div id="qr-panel"></div>
    </div>
  `);

  if (a.can_request_access) {
    sections.push(`
      <div class="glass-card venue-panel-section">
        <div class="venue-panel-title" style="font-weight: 700;">Request Access</div>
        <p style="color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 10px;">Ask the organizer to let you in.</p>
        <form id="request-access-form">
          <textarea class="venue-request-note" id="request-note" placeholder="Optional note (e.g. who invited you)"></textarea>
          <button type="submit" class="btn btn-primary btn-sm" style="margin-top: 10px;">Send Request</button>
        </form>
      </div>
    `);
  }

  if (venue.membership_plans && venue.membership_plans.length) {
    sections.push(`
      <div class="glass-card venue-panel-section">
        <div class="venue-panel-title" style="font-weight: 700;">Membership Plans</div>
        <div style="margin-top: 10px;">
          ${venue.membership_plans.map(p => `
            <div class="venue-list-item">
              <div>
                <div style="font-weight: 700;">${escapeHtml(p.name)} <span class="badge badge-amber">$${p.price.toFixed(2)}/${escapeHtml(p.interval)}</span></div>
                ${p.perks ? `<div style="font-size: 0.78rem; color: var(--text-muted);">${escapeHtml(p.perks)}</div>` : ''}
              </div>
              <button class="btn btn-primary btn-sm join-plan-btn" data-plan-id="${p.id}">Join</button>
            </div>
          `).join('')}
        </div>
      </div>
    `);
  }

  if (venue.products && venue.products.length) {
    sections.push(`
      <div class="glass-card venue-panel-section">
        <div class="venue-panel-title" style="font-weight: 700;">Products</div>
        <div style="margin-top: 10px;">
          ${venue.products.map(p => `
            <div class="venue-list-item">
              <div>
                <div style="font-weight: 700;">${escapeHtml(p.name)} <span class="badge badge-amber">$${p.price.toFixed(2)}</span></div>
                ${p.description ? `<div style="font-size: 0.78rem; color: var(--text-muted);">${escapeHtml(p.description)}</div>` : ''}
              </div>
              <button class="btn btn-primary btn-sm buy-product-btn" data-product-id="${p.id}">Buy</button>
            </div>
          `).join('')}
        </div>
      </div>
    `);
  }

  panel.innerHTML = sections.join('');
  bindPanelActions();
}

function bindPanelActions() {
  const observeBtn = document.getElementById('observe-btn');
  if (observeBtn) {
    observeBtn.addEventListener('click', () => {
      const ev = venue.active_event;
      document.getElementById('observe-panel').innerHTML = ev ? `
        <div class="venue-list-item" style="margin-top: 12px;">
          <div>
            <div style="font-weight: 700;">🎉 ${escapeHtml(ev.title)}</div>
            <div style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(ev.type)}${ev.organizer_name ? ` · hosted by ${escapeHtml(ev.organizer_name)}` : ''}</div>
          </div>
        </div>
      ` : '';
      showToast("You're watching from the sidelines -- ask for access to join in.", 'info');
    });
  }

  const qrBtn = document.getElementById('qr-btn');
  if (qrBtn) {
    qrBtn.addEventListener('click', async () => {
      try {
        const res = await fetch(`/api/v/${encodeURIComponent(venue.slug)}/qr-pass`, { headers: patronHeaders() });
        const data = await res.json();
        if (!res.ok) throw new Error(errorDetail(data, 'Failed to load QR pass.'));
        document.getElementById('qr-panel').innerHTML = `
          <div class="venue-qr-pass">
            <div style="font-size: 0.85rem; color: var(--text-secondary);">Show this to staff at the door:</div>
            <div class="venue-qr-token">${escapeHtml(data.token)}</div>
          </div>
        `;
      } catch (err) {
        showToast(err.message || 'Failed to load QR pass.', 'error');
      }
    });
  }

  const requestForm = document.getElementById('request-access-form');
  if (requestForm) {
    requestForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const note = document.getElementById('request-note').value.trim();
      try {
        const res = await fetch(`/api/v/${encodeURIComponent(venue.slug)}/access-requests`, {
          method: 'POST',
          headers: patronHeaders(),
          body: JSON.stringify({ event_id: venue.active_event ? venue.active_event.id : null, note: note || null }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(errorDetail(data, 'Failed to send request.'));
        requestForm.innerHTML = `<div style="color: var(--accent-emerald); font-size: 0.9rem;">✓ Request sent -- pending approval.</div>`;
        showToast('Access request sent.', 'success');
      } catch (err) {
        showToast(err.message || 'Failed to send request.', 'error');
      }
    });
  }

  document.querySelectorAll('.join-plan-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        const res = await fetch(`/api/v/${encodeURIComponent(venue.slug)}/membership-plans/${btn.dataset.planId}/join`, {
          method: 'POST',
          headers: patronHeaders(),
          body: JSON.stringify({ payment_method: 'mock_card' }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(errorDetail(data, 'Failed to join.'));
        showToast(data.message || 'Joined!', 'success');
        await loadVenue();
      } catch (err) {
        showToast(err.message || 'Failed to join plan.', 'error');
      }
    });
  });

  document.querySelectorAll('.buy-product-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        const res = await fetch(`/api/v/${encodeURIComponent(venue.slug)}/products/${btn.dataset.productId}/purchase`, {
          method: 'POST',
          headers: patronHeaders(),
          body: JSON.stringify({ payment_method: 'mock_card' }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(errorDetail(data, 'Failed to purchase.'));
        showToast(data.message || 'Purchased!', 'success');
        await loadVenue();
      } catch (err) {
        showToast(err.message || 'Failed to purchase.', 'error');
      }
    });
  });
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// FastAPI's own 422 validation errors shape `detail` as an array of
// {msg, loc, ...} objects rather than the plain string our own
// HTTPException(...) calls send -- stringify either shape instead of
// letting a validation error render as the literal text "[object Object]".
function errorDetail(data, fallback) {
  const detail = data && data.detail;
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(d => d.msg || JSON.stringify(d)).join('; ');
  return fallback;
}
