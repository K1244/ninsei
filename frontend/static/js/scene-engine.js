/**
 * Shared pixelart "walkable scene" engine (PLAN.md section 10) -- the WASD/
 * click-to-move + walk-to-a-point-then-fire-a-callback mechanics originally
 * built for room.js, factored out so venue.js can reuse the exact same
 * movement feel instead of re-implementing it.
 *
 * Deliberately owns only motion state, not DOM construction -- each page
 * still builds its own stage/decorations/hotspots however fits its own
 * layout (see room.js's ROOM_LAYOUT vs venue.js's FURNITURE), and still owns
 * its own hotspot-trigger logic. This module just answers "where is the
 * player right now" every frame and moves them there.
 */

function fitStageToViewport(stageEl, worldW, worldH) {
  const viewport = stageEl.parentElement;
  const scale = Math.min(1, viewport.clientWidth / worldW);
  stageEl.style.transform = `scale(${scale})`;
  viewport.style.height = `${worldH * scale}px`;
  return scale;
}

/**
 * @param stageEl the fixed-resolution world element (click-to-move coords are
 *   read relative to it, scaled by worldW)
 * @param playerEl the `.room-player` element (see room.css) whose position/
 *   sprite this engine drives every frame
 * @param bounds {minX, maxX, minY, maxY} walkable area in world pixels
 * @param worldW world width in px, used to unscale click coordinates
 * @param speed px/sec in world space
 */
function createWalkableScene({ stageEl, playerEl, bounds, worldW, speed = 260, arriveEpsilon = 6 }) {
  const player = { x: 0, y: 0, avatarFile: null };
  let moveTarget = null;
  let onArrive = null;
  const heldKeys = new Set();
  let lastFrameTime = null;

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  function setMoveTarget(x, y, arriveCallback) {
    moveTarget = { x: clamp(x, bounds.minX, bounds.maxX), y: clamp(y, bounds.minY, bounds.maxY) };
    onArrive = arriveCallback || null;
  }

  // Convenience for hotspots: walk to a fixed "stand here" point, then fire
  // the hotspot's action -- mirrors room.js's original walkToHotspot.
  function walkTo(point, arriveCallback) {
    setMoveTarget(point.x, point.y, arriveCallback);
  }

  function bindMovementInput() {
    window.addEventListener('keydown', (e) => {
      const key = e.key.toLowerCase();
      if (['arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'w', 'a', 's', 'd'].includes(key)) {
        heldKeys.add(key);
        moveTarget = null; // keyboard overrides an in-flight click-to-move
        e.preventDefault();
      }
    });
    window.addEventListener('keyup', (e) => heldKeys.delete(e.key.toLowerCase()));
  }

  // Click/tap-to-move on empty floor. `ignoreSelector` lets hotspot buttons
  // (separate elements) opt out so a hotspot click never also triggers a
  // walk-to-click-point.
  function attachClickToMove(ignoreSelector) {
    stageEl.addEventListener('click', (e) => {
      if (ignoreSelector && e.target.closest(ignoreSelector)) return;
      const rect = stageEl.getBoundingClientRect();
      const scale = rect.width / worldW;
      const x = (e.clientX - rect.left) / scale;
      const y = (e.clientY - rect.top) / scale;
      setMoveTarget(x, y, null);
    });
  }

  function keyboardDirection() {
    let x = 0, y = 0;
    if (heldKeys.has('arrowleft') || heldKeys.has('a')) x -= 1;
    if (heldKeys.has('arrowright') || heldKeys.has('d')) x += 1;
    if (heldKeys.has('arrowup') || heldKeys.has('w')) y -= 1;
    if (heldKeys.has('arrowdown') || heldKeys.has('s')) y += 1;
    if (x !== 0 && y !== 0) { x *= Math.SQRT1_2; y *= Math.SQRT1_2; }
    return { x, y };
  }

  function renderPlayer() {
    playerEl.style.left = `${player.x}px`;
    playerEl.style.top = `${player.y}px`;
    if (!player.avatarFile) return;
    const img = playerEl.querySelector('img');
    const wantedSrc = `/static/${player.avatarFile}`;
    if (!img.src.endsWith(player.avatarFile)) img.src = wantedSrc;
  }

  function tick(now) {
    if (lastFrameTime === null) lastFrameTime = now;
    const dt = Math.min((now - lastFrameTime) / 1000, 0.05); // clamp for tab-switch stalls
    lastFrameTime = now;

    const keyboardVec = keyboardDirection();
    if (keyboardVec.x !== 0 || keyboardVec.y !== 0) {
      player.x = clamp(player.x + keyboardVec.x * speed * dt, bounds.minX, bounds.maxX);
      player.y = clamp(player.y + keyboardVec.y * speed * dt, bounds.minY, bounds.maxY);
      if (keyboardVec.x < 0) playerEl.classList.add('facing-left');
      if (keyboardVec.x > 0) playerEl.classList.remove('facing-left');
    } else if (moveTarget) {
      const dx = moveTarget.x - player.x;
      const dy = moveTarget.y - player.y;
      const dist = Math.hypot(dx, dy);
      if (dist <= arriveEpsilon) {
        player.x = moveTarget.x;
        player.y = moveTarget.y;
        moveTarget = null;
        const callback = onArrive;
        onArrive = null;
        if (callback) callback();
      } else {
        const step = Math.min(speed * dt, dist);
        player.x += (dx / dist) * step;
        player.y += (dy / dist) * step;
        if (dx < 0) playerEl.classList.add('facing-left');
        if (dx > 0) playerEl.classList.remove('facing-left');
      }
    }

    renderPlayer();
    requestAnimationFrame(tick);
  }

  function start() {
    requestAnimationFrame(tick);
  }

  return { player, setMoveTarget, walkTo, bindMovementInput, attachClickToMove, renderPlayer, start };
}

window.SceneEngine = { fitStageToViewport, createWalkableScene };
