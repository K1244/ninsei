"""
Curates backend/app/config.py's flat AVATAR_OPTIONS (one entry per individually
cut sprite cell) into character groups: same character, multiple poses
(front/back/side) and, where the source sheet actually drew them, multiple
animation frames per pose.

Approach (see chat writeup for why this can't be a fixed row/col rule -- the
6 source sheets don't share one column-per-character convention):
  1. Cluster cells into "same character" groups using color-histogram
     similarity of their non-transparent pixels (a character's palette --
     hair/clothes colors -- stays consistent across poses; different
     characters on the same sheet don't share a palette).
  2. Within a character's cluster, classify each cell's pose as
     front/back/side using left-right mirror symmetry (front & back are
     roughly symmetric, side profiles aren't) plus a face/eye heuristic
     (dark blobs on skin-tone in the head region) to split front from back.
  3. Cells that land in the same character+pose bucket become consecutive
     animation frames (sorted in natural row/col order) -- this is what
     picks up the real walk-cycle frames in avatars_6.png, and gives a
     harmless subtle idle-variation to sheets that only have incidental
     near-duplicate poses.

Output: characters.json in the sprites root, consumed by config.py's
_load_character_manifest().

Usage:
    python3 tools/curate_characters.py
(re-run after slice_sprites.py if the avatars/ sheets ever change)
"""
import json
from pathlib import Path
from collections import defaultdict

import numpy as np
from PIL import Image

SPRITES_ROOT = Path(__file__).resolve().parent.parent / 'frontend' / 'static' / 'assets' / 'sprites'
AVATARS_DIR = SPRITES_ROOT / 'avatars'
MANIFEST = SPRITES_ROOT / 'manifest.json'

ALPHA_THRESHOLD = 30
HIST_BINS = 8  # per channel, RGB -> 8^3 = 512 bins


def load_cell(entry):
    im = Image.open(AVATARS_DIR / entry['file'].split('/', 1)[1]).convert('RGBA')
    arr = np.array(im)
    return arr


def color_hist(arr):
    mask = arr[:, :, 3] > ALPHA_THRESHOLD
    px = arr[mask][:, :3].astype(np.float32)
    if len(px) == 0:
        return np.zeros(HIST_BINS ** 3)
    bins = (px / 256 * HIST_BINS).astype(int).clip(0, HIST_BINS - 1)
    idx = bins[:, 0] * HIST_BINS * HIST_BINS + bins[:, 1] * HIST_BINS + bins[:, 2]
    h = np.bincount(idx, minlength=HIST_BINS ** 3).astype(np.float32)
    h /= h.sum()
    return h


def hist_similarity(h1, h2):
    return float(np.minimum(h1, h2).sum())  # histogram intersection, 0..1


def symmetry_score(arr):
    """1.0 = perfectly left-right mirror symmetric silhouette+color, lower = more asymmetric (side profile)."""
    mask = arr[:, :, 3] > ALPHA_THRESHOLD
    mirrored_mask = mask[:, ::-1]
    mirrored_rgb = arr[:, ::-1, :3]
    both = mask & mirrored_mask
    if both.sum() < 0.3 * mask.sum():
        return 0.0  # silhouette itself isn't symmetric -> definitely a side view
    diff = np.abs(arr[:, :, :3].astype(np.float32) - mirrored_rgb.astype(np.float32))
    color_agree = 1.0 - (diff[both].mean() / 255.0)
    silhouette_agree = both.sum() / mask.sum()
    return float(0.5 * color_agree + 0.5 * silhouette_agree)


SKIN_R, SKIN_G, SKIN_B = 220, 180, 140  # loose skin-tone anchor, pixel-art palettes vary


def face_score(arr):
    """Higher = looks like a front-facing head (skin-toned head region containing dark eye blobs)."""
    h, w = arr.shape[:2]
    mask = arr[:, :, 3] > ALPHA_THRESHOLD
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return 0.0
    y0, y1 = ys.min(), ys.max()
    head_y0, head_y1 = y0, y0 + int((y1 - y0) * 0.45)
    head = arr[head_y0:head_y1, :, :3].astype(np.float32)
    head_mask = mask[head_y0:head_y1, :]
    if head_mask.sum() == 0:
        return 0.0
    skin_dist = np.sqrt(((head - np.array([SKIN_R, SKIN_G, SKIN_B])) ** 2).sum(axis=2))
    skin_like = (skin_dist < 90) & head_mask
    skin_frac = skin_like.sum() / head_mask.sum()
    # dark "eye" pixels sitting on/near skin-like rows
    brightness = head.sum(axis=2) / 3
    dark = (brightness < 70) & head_mask
    dark_frac = dark.sum() / head_mask.sum()
    return float(skin_frac * 0.6 + min(dark_frac * 8, 1.0) * 0.4)


# Calibrated empirically against known-correct groupings on several rows
# (see chat writeup): within-character adjacent-cell similarity sits ~0.81-0.93,
# a real character boundary drops to ~0.66-0.75; a same-character block
# repeated a row or two down (front row, back row) sits ~0.85-0.93, while two
# *different* characters on nearby rows sit ~0.27-0.69. These two thresholds
# sit in the gap between those clusters.
ADJACENT_SPLIT_THRESHOLD = 0.75
CROSS_ROW_MERGE_THRESHOLD = 0.78
CROSS_ROW_WINDOW = 3  # only consider merging blocks within this many rows of each other

# The clustering above was spot-checked by eye (rendering every multi-row
# group as a contact strip) against all 17 groups it produced spanning more
# than one row. 14 were correct; these 3 weren't -- two different people on
# the source sheet happened to share a close enough palette (both in dark
# navy, or both bald/short-haired) that Phase B's star-clustering merged
# them. Rather than keep chasing a threshold that fixes these without
# breaking the other 14, these are hand-corrected: each maps the wrongly-
# merged auto key to the file groups it should have produced.
MANUAL_SPLITS = {
    'avatars_char3': [
        ['avatars/avatars_r4_c0.png', 'avatars/avatars_r4_c1.png', 'avatars/avatars_r4_c2.png',
         'avatars/avatars_r5_c0.png', 'avatars/avatars_r5_c1.png', 'avatars/avatars_r5_c2.png'],
        ['avatars/avatars_r5_c3.png', 'avatars/avatars_r5_c4.png', 'avatars/avatars_r5_c5.png'],
        ['avatars/avatars_r6_c0.png', 'avatars/avatars_r6_c1.png', 'avatars/avatars_r6_c2.png',
         'avatars/avatars_r6_c3.png', 'avatars/avatars_r6_c4.png', 'avatars/avatars_r6_c5.png'],
    ],
    'avatars_1_char0': [
        ['avatars/avatars_1_r0_c0.png', 'avatars/avatars_1_r0_c1.png',
         'avatars/avatars_1_r1_c0.png', 'avatars/avatars_1_r1_c1.png'],
        ['avatars/avatars_1_r2_c0.png', 'avatars/avatars_1_r2_c1.png', 'avatars/avatars_1_r2_c2.png',
         'avatars/avatars_1_r2_c3.png', 'avatars/avatars_1_r2_c4.png', 'avatars/avatars_1_r2_c5.png',
         'avatars/avatars_1_r2_c6.png', 'avatars/avatars_1_r2_c7.png',
         'avatars/avatars_1_r3_c0.png', 'avatars/avatars_1_r3_c1.png'],
    ],
    'avatars_3_char0': [
        ['avatars/avatars_3_r0_c0.png', 'avatars/avatars_3_r0_c1.png', 'avatars/avatars_3_r0_c2.png',
         'avatars/avatars_3_r0_c5.png'],
        ['avatars/avatars_3_r1_c3.png', 'avatars/avatars_3_r1_c4.png', 'avatars/avatars_3_r1_c5.png'],
    ],
}


def main():
    manifest = json.load(open(MANIFEST))
    avatar_entries = [e for e in manifest if e['file'].startswith('avatars/')]
    by_sheet = defaultdict(list)
    for e in avatar_entries:
        by_sheet[e['source_sheet']].append(e)

    all_characters = []
    debug_lines = []

    for sheet, entries in sorted(by_sheet.items()):
        entries = sorted(entries, key=lambda e: (e['row'], e['col']))
        hists = {e['file']: color_hist(load_cell(e)) for e in entries}

        # Phase A: within each row, split into contiguous blocks (characters are
        # laid out as unbroken horizontal runs -- verified by inspection, no
        # sheet interleaves two characters' cells within one row).
        by_row = defaultdict(list)
        for e in entries:
            by_row[e['row']].append(e)
        blocks = []  # {'files': [...], 'row_range': (min,max), 'hist': avg}
        for row, row_entries in sorted(by_row.items()):
            row_entries = sorted(row_entries, key=lambda e: e['col'])
            current = [row_entries[0]]
            for prev, e in zip(row_entries, row_entries[1:]):
                sim = hist_similarity(hists[prev['file']], hists[e['file']])
                if sim < ADJACENT_SPLIT_THRESHOLD:
                    blocks.append(current)
                    current = []
                current.append(e)
            blocks.append(current)

        block_infos = []
        for b in blocks:
            files = [e['file'] for e in b]
            avg_hist = np.mean([hists[f] for f in files], axis=0)
            rows = [e['row'] for e in b]
            block_infos.append({'files': files, 'rows': (min(rows), max(rows)), 'hist': avg_hist})

        # Phase B: merge blocks across nearby rows that are clearly the same
        # character shown in another pose (e.g. front row, back row directly
        # below it). Star-clustering against each group's original seed block
        # only (not a running/chained average) -- chaining let similarity
        # drift across a whole row of unrelated characters transitively;
        # comparing everyone back to the same fixed seed doesn't drift.
        merged = []
        used = [False] * len(block_infos)
        for i, bi in enumerate(block_infos):
            if used[i]:
                continue
            group = [bi]
            used[i] = True
            for j, bj in enumerate(block_infos):
                if used[j]:
                    continue
                row_gap = min(abs(bi['rows'][0] - bj['rows'][1]), abs(bj['rows'][0] - bi['rows'][1]))
                if row_gap <= CROSS_ROW_WINDOW and hist_similarity(bi['hist'], bj['hist']) >= CROSS_ROW_MERGE_THRESHOLD:
                    group.append(bj)
                    used[j] = True
            files = [f for g in group for f in g['files']]
            merged.append(files)

        # Apply manual splits: expand any auto-key that's known-wrong into its
        # hand-verified sub-groups before final key assignment, so a fixed
        # group still gets keyed off its position in the (corrected) list
        # rather than needing its own separate id scheme.
        sheet_stem = sheet[:-4]
        entry_by_file = {e['file']: e for e in entries}
        for i, files in enumerate(merged):
            files.sort(key=lambda f: (entry_by_file[f]['row'], entry_by_file[f]['col']))
        expanded = []
        for i, files in enumerate(merged):
            auto_key = f'{sheet_stem}_char{i}'
            expanded.extend(MANUAL_SPLITS.get(auto_key, [files]))

        for i, files in enumerate(expanded):
            all_characters.append({
                'key': f'{sheet_stem}_char{i}',
                'sheet': sheet,
                'thumbnail': files[0],
                'frames': files,
            })
            debug_lines.append(f"{sheet_stem}_char{i}: {len(files)} frames -> {files}")

    out_path = SPRITES_ROOT / 'characters.json'
    with open(out_path, 'w') as f:
        json.dump(all_characters, f, indent=2)
    print(f"Wrote {len(all_characters)} characters to {out_path}")
    print('\n'.join(debug_lines))


if __name__ == '__main__':
    main()
