/**
 * Venue hub (PLAN.md section 6's directory, browsed as a card grid rather
 * than a literal map for MVP -- the plan explicitly allows either). Pulls
 * GET /api/venues (public, no auth -- see directory_router.py) and renders
 * one card per open venue.
 */

const MODE_BADGE_CLASS = {
  public: 'badge-green',
  members_only: 'badge-purple',
  private_event: 'badge-amber',
  invite_only: 'badge-purple',
  observer_allowed: 'badge-amber',
  closed: 'badge-rose',
};

const MODE_LABEL = {
  public: 'Open',
  members_only: 'Members Only',
  private_event: 'Private Event',
  invite_only: 'Invite Only',
  observer_allowed: 'Observe Only',
  closed: 'Closed',
};

// Client-side mirror of config.SCENE_THEME_SOURCE_SHEETS, picking one
// representative sprite per theme for the card art rather than a full tile
// render (that's the venue scene page's job, not the hub's).
const THEME_ART = {
  pub: '/static/assets/sprites/venue/venue_bar_tools_r0_c0.png',
  bar: '/static/assets/sprites/venue/venue_bar_tools_r0_c0.png',
  club: '/static/assets/sprites/venue/venue_bar_items_r0_c3.png',
  lounge: '/static/assets/sprites/venue/venue_underground_r3_c2.png',
};

document.addEventListener('DOMContentLoaded', async () => {
  const grid = document.getElementById('venues-grid');
  try {
    const res = await fetch('/api/venues');
    if (!res.ok) throw new Error('failed');
    const venues = await res.json();
    renderVenues(grid, venues);
  } catch (err) {
    grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: var(--accent-rose); padding: 40px;">Failed to load venues.</div>';
  }
});

function renderVenues(grid, venues) {
  if (!venues || venues.length === 0) {
    grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 40px;">No venues open right now -- check back later.</div>';
    return;
  }

  grid.innerHTML = venues.map(v => {
    const art = THEME_ART[v.scene_theme] || THEME_ART.pub;
    const modeClass = MODE_BADGE_CLASS[v.mode] || 'badge-purple';
    const modeLabel = MODE_LABEL[v.mode] || v.mode;
    const eventLine = v.active_event
      ? `<div class="venue-card-event">🎉 ${escapeHtml(v.active_event.title)}</div>`
      : '';

    return `
      <a class="glass-card venue-card" href="/venue/${encodeURIComponent(v.slug)}">
        <div class="venue-card-art"><img src="${art}" alt="" /></div>
        <div class="venue-card-body">
          <div class="venue-card-name">${escapeHtml(v.name)}</div>
          ${v.description ? `<div class="venue-card-desc">${escapeHtml(v.description)}</div>` : ''}
          <div class="venue-card-badges">
            <span class="badge ${modeClass}">${escapeHtml(modeLabel)}</span>
          </div>
          ${eventLine}
        </div>
      </a>
    `;
  }).join('');
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
