/**
 * Pixelart landing room (PLAN.md section 2/10): a fixed-resolution "world"
 * (see STAGE_W/STAGE_H) that gets CSS-scaled to fit the viewport, so every
 * sprite/hotspot below is placed with plain pixel coordinates rather than
 * fighting responsive layout math. Movement is WASD/arrow keys (continuous,
 * while held) or click/tap-to-move (walk toward the clicked point); clicking
 * a hotspot walks the player to a spot in front of it and then fires that
 * hotspot's action, mostly so it *feels* like a room instead of a menu.
 */

const STAGE_W = 1000;
const STAGE_H = 640;
const WALK_BOUNDS = { minX: 60, maxX: 940, minY: 360, maxY: 610 };
const MOVE_SPEED = 260; // px/sec in world space

const PATRON_TOKEN_KEY = 'clubowna_patron_token';
const FALLBACK_AVATAR_FILE = 'assets/sprites/avatars/avatars_r0_c0.png';

// Everything on the back wall / floor that isn't the player. Interactive
// items carry an `action`; decorations are just atmosphere.
const ROOM_LAYOUT = {
  decorations: [
    { sprite: 'assets/sprites/room/home_items_r2_c0.png', x: 50, y: 30, w: 170 },
    { sprite: 'assets/sprites/room/home_items_r1_c0.png', x: 150, y: 470, w: 300 },
    { sprite: 'assets/sprites/room/home_items_r1_c2.png', x: 640, y: 150, w: 150 },
  ],
  hotspots: [
    {
      id: 'bed', label: 'Rest a moment', sprite: 'assets/sprites/room/home_items_r0_c0.png',
      x: 40, y: 220, w: 250, walkTo: { x: 190, y: 430 },
    },
    {
      id: 'computer', label: 'Enter the system', sprite: 'assets/sprites/room/home_items_r0_c2.png',
      x: 430, y: 190, w: 280, walkTo: { x: 560, y: 440 },
    },
    {
      id: 'poster', label: 'Read the poster', sprite: 'assets/sprites/room/home_items_r0_c3.png',
      x: 300, y: 50, w: 120, walkTo: { x: 340, y: 380 },
    },
    {
      id: 'wardrobe', label: 'Change your look', sprite: 'assets/sprites/room/home_items_r0_c4.png',
      x: 820, y: 60, w: 150, walkTo: { x: 880, y: 380 },
    },
    {
      id: 'door', label: 'Head out', sprite: 'assets/sprites/room/home_items_r2_c1.png',
      x: 860, y: 260, w: 120, walkTo: { x: 910, y: 440 },
    },
  ],
};

let playerEl, stageEl, scene;

document.addEventListener('DOMContentLoaded', async () => {
  stageEl = document.getElementById('room-stage');
  playerEl = document.createElement('div');
  playerEl.className = 'room-player';
  playerEl.innerHTML = `<img alt="Your character" />`;

  scene = SceneEngine.createWalkableScene({
    stageEl, playerEl, bounds: WALK_BOUNDS, worldW: STAGE_W, speed: MOVE_SPEED,
  });
  scene.player.x = 500;
  scene.player.y = 560;
  scene.player.avatarFile = FALLBACK_AVATAR_FILE;

  buildStage();
  SceneEngine.fitStageToViewport(stageEl, STAGE_W, STAGE_H);
  window.addEventListener('resize', () => SceneEngine.fitStageToViewport(stageEl, STAGE_W, STAGE_H));

  await identifyPatron();
  scene.renderPlayer();

  scene.bindMovementInput();
  scene.attachClickToMove('.room-hotspot');
  scene.start();

  bindModalCloseButtons();
});

// --- Stage construction -----------------------------------------------

function buildStage() {
  ROOM_LAYOUT.decorations.forEach(d => {
    const img = document.createElement('img');
    img.src = `/static/${d.sprite}`;
    img.className = 'room-sprite';
    img.alt = '';
    img.style.left = `${d.x}px`;
    img.style.top = `${d.y}px`;
    img.style.width = `${d.w}px`;
    stageEl.appendChild(img);
  });

  ROOM_LAYOUT.hotspots.forEach(h => {
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
    stageEl.appendChild(btn);
  });

  stageEl.appendChild(playerEl);
}

// --- Player identity -----------------------------------------------------

async function identifyPatron() {
  try {
    const savedToken = localStorage.getItem(PATRON_TOKEN_KEY);
    const res = await fetch('/api/users/identify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: savedToken }),
    });
    if (!res.ok) throw new Error('identify failed');
    const user = await res.json();
    localStorage.setItem(PATRON_TOKEN_KEY, user.token);
    if (user.avatar) {
      scene.player.avatarFile = `assets/sprites/avatars/${user.avatar}.png`;
    }
  } catch (err) {
    // Anonymous browsing still works fine with the fallback sprite -- see
    // user_service.get_optional_user's "never raises" contract server-side.
    console.warn('[room] identify failed, continuing anonymously:', err);
  }
}

// --- Hotspot actions ---------------------------------------------------

function triggerHotspot(id) {
  switch (id) {
    case 'computer':
      openModal('computer-modal');
      break;
    case 'poster':
      openModal('poster-modal');
      break;
    case 'wardrobe':
      openAvatarPicker();
      break;
    case 'door':
      window.location.href = '/venues';
      break;
    case 'bed':
      showToast("You lie down for a second... but the night's calling. Head to the door when you're ready.", 'info');
      break;
  }
}

// --- Avatar picker (wardrobe hotspot) -----------------------------------

async function openAvatarPicker() {
  openModal('avatar-modal');
  const grid = document.getElementById('avatar-grid');
  if (grid.dataset.loaded === 'true') return;

  try {
    const res = await fetch('/api/users/avatar-options');
    if (!res.ok) throw new Error('failed');
    const options = await res.json();
    grid.innerHTML = options.map(o => `
      <div class="avatar-grid-item" data-key="${escapeHtml(o.key)}" data-file="${escapeHtml(o.file)}">
        <img src="/static/${escapeHtml(o.file)}" alt="${escapeHtml(o.key)}" loading="lazy" />
      </div>
    `).join('');
    grid.dataset.loaded = 'true';

    grid.querySelectorAll('.avatar-grid-item').forEach(item => {
      item.addEventListener('click', () => selectAvatar(item.dataset.key, item.dataset.file, grid));
    });
  } catch (err) {
    grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: var(--accent-rose);">Failed to load avatars.</div>';
  }
}

async function selectAvatar(key, file, grid) {
  try {
    const token = localStorage.getItem(PATRON_TOKEN_KEY);
    const res = await fetch('/api/users/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-User-Token': token || '' },
      body: JSON.stringify({ avatar: key }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || 'Failed to save avatar.');
    }
    scene.player.avatarFile = file;
    scene.renderPlayer();
    grid.querySelectorAll('.avatar-grid-item').forEach(el => el.classList.toggle('selected', el.dataset.key === key));
    showToast('Look saved.', 'success');
  } catch (err) {
    showToast(err.message || 'Failed to save avatar.', 'error');
  }
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
