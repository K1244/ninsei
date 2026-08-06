"""
Cuts the raw AI-generated reference sheets in png_assets/ (avatars, room
furniture, event props, venue tiles -- see PLAN.md) into individual
transparent-background sprite PNGs, plus a manifest.json describing where
each one came from.

Why this works without manual per-sheet grid calibration: every sheet
already carries real alpha transparency around each character/item (verified
by inspection -- corners are alpha=0, content is alpha=255, only a thin
antialiased edge in between). So instead of guessing a fixed column/row grid
per file, this just finds connected components in the alpha channel and
crops each one's bounding box. Components are then clustered into rows by
centroid Y (components within half a row-height of each other are treated as
the same row) and sorted left-to-right within each row, purely so the output
filenames read in the same order a human scanning the sheet would use --
row/col here is a naming convenience, not something read back off a rigid
grid.

Usage:
    python3 tools/slice_sprites.py <input_dir> <output_dir>

Input dir: raw sheets (avatars.png, home_items.png, ...).
Output dir: gets one subfolder per category (avatars/room/props/venue) full
of cropped PNGs, plus manifest.json at its root.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

# Which category folder each source sheet's pieces land in.
CATEGORY_BY_SHEET = {
    "avatars.png": "avatars",
    "avatars_1.png": "avatars",
    "avatars_3.png": "avatars",
    "avatars4.png": "avatars",
    "avatars_5.png": "avatars",
    "avatars_6.png": "avatars",
    "home_items.png": "room",
    "home_items_2.png": "room",
    "items.png": "props",
    "items_1.png": "props",
    "venue_bar_items.png": "venue",
    "venue_bar_tools.png": "venue",
    "venue_club_tools.png": "venue",
    "venue_underground.png": "venue",
    # home_room_crazy.png deliberately excluded -- it's a single finished
    # mood-board illustration, not a sheet of cuttable pieces.
}

ALPHA_THRESHOLD = 30       # foreground = alpha > this
MIN_COMPONENT_AREA = 300   # px^2 -- filters antialiasing specks, not real items
PADDING = 3                # px of breathing room kept around each crop
ROW_CLUSTER_FRACTION = 0.5  # fraction of median component height for row grouping


def find_components(alpha: np.ndarray):
    mask = alpha > ALPHA_THRESHOLD
    # A 1px closing joins antialiased gaps within one character (e.g. a
    # thin neck) without bridging the visibly wider gaps between separate
    # characters/items on every sheet we checked.
    mask = ndimage.binary_closing(mask, structure=np.ones((3, 3)))
    labeled, n = ndimage.label(mask, structure=np.ones((3, 3)))
    components = []
    for label_id in range(1, n + 1):
        ys, xs = np.where(labeled == label_id)
        area = len(ys)
        if area < MIN_COMPONENT_AREA:
            continue
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        components.append({
            "label_id": label_id,
            "bbox": (x0, y0, x1 + 1, y1 + 1),
            "centroid": (float(xs.mean()), float(ys.mean())),
            "height": y1 - y0 + 1,
            "area": area,
        })
    return components, labeled


def assign_rows_cols(components):
    if not components:
        return []
    median_h = float(np.median([c["height"] for c in components]))
    threshold = max(median_h * ROW_CLUSTER_FRACTION, 8.0)

    by_y = sorted(components, key=lambda c: c["centroid"][1])
    rows = []
    current_row = [by_y[0]]
    current_row_y = by_y[0]["centroid"][1]
    for c in by_y[1:]:
        if abs(c["centroid"][1] - current_row_y) <= threshold:
            current_row.append(c)
            # running mean keeps the threshold anchored to the row, not just
            # the first item in it, so a slightly-sloped row doesn't drift
            # into starting a spurious new row partway across.
            current_row_y = sum(x["centroid"][1] for x in current_row) / len(current_row)
        else:
            rows.append(current_row)
            current_row = [c]
            current_row_y = c["centroid"][1]
    rows.append(current_row)

    for row_idx, row in enumerate(rows):
        row.sort(key=lambda c: c["centroid"][0])
        for col_idx, c in enumerate(row):
            c["row"] = row_idx
            c["col"] = col_idx
    return components


def slice_sheet(path: Path, out_root: Path, manifest: list):
    category = CATEGORY_BY_SHEET.get(path.name)
    if category is None:
        return

    im = Image.open(path).convert("RGBA")
    arr = np.array(im)
    alpha = arr[:, :, 3]
    w, h = im.size

    components, labeled = find_components(alpha)
    components = assign_rows_cols(components)

    out_dir = out_root / category
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_stem = path.stem

    for c in components:
        x0, y0, x1, y1 = c["bbox"]
        px0, py0 = max(0, x0 - PADDING), max(0, y0 - PADDING)
        px1, py1 = min(w, x1 + PADDING), min(h, y1 + PADDING)

        crop_arr = arr[py0:py1, px0:px1].copy()
        # Zero out any pixels in this crop that belong to a *different*
        # component (bounding boxes can slightly overlap when e.g. a wide
        # hat leans into a neighboring cell) so nothing bleeds in from
        # whatever sprite sits next door.
        label_crop = labeled[py0:py1, px0:px1]
        other = (label_crop != c["label_id"]) & (label_crop != 0)
        crop_arr[other, 3] = 0

        out_name = f"{sheet_stem}_r{c['row']}_c{c['col']}.png"
        Image.fromarray(crop_arr).save(out_dir / out_name, optimize=True)

        manifest.append({
            "file": f"{category}/{out_name}",
            "source_sheet": path.name,
            "row": c["row"],
            "col": c["col"],
            "width": px1 - px0,
            "height": py1 - py0,
            "source_bbox": [x0, y0, x1, y1],
        })


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_dir> <output_dir>")
        sys.exit(1)
    in_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list = []
    for name in sorted(CATEGORY_BY_SHEET):
        path = in_dir / name
        if not path.exists():
            print(f"  SKIP (not found): {name}")
            continue
        before = len(manifest)
        slice_sheet(path, out_dir, manifest)
        print(f"  {name}: {len(manifest) - before} sprites")

    manifest.sort(key=lambda m: (m["file"]))
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nTotal: {len(manifest)} sprites. Manifest: {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
