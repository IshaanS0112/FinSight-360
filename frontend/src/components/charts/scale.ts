/** Scales, ticks and label placement shared by the hand-drawn SVG charts. */

/** Maps a data domain linearly onto a pixel range. */
export function linear(domain: [number, number], range: [number, number]): (value: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (value: number) => r0 + (value - d0) * k;
}

/** The [min, max] of the values, widened by `fraction` of the span on each side. */
export function paddedExtent(values: number[], fraction = 0.06): [number, number] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min || Math.abs(max) || 1) * fraction;
  return [min - pad, max + pad];
}

/** About `count` round tick values (1, 2 or 5 times a power of ten) inside [min, max]. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  const raw = (max - min || Math.abs(max) || 1) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 1e-9; value += step) {
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks;
}

export interface LabelRequest {
  id: string;
  x: number;
  y: number;
  text: string;
}

export interface PlacedLabel extends LabelRequest {
  anchor: "start" | "end" | "middle";
  lx: number;
  ly: number;
}

type Box = [number, number, number, number];

const overlaps = (a: Box, b: Box) => !(a[2] < b[0] || a[0] > b[2] || a[3] < b[1] || a[1] > b[3]);

/**
 * Places labels in priority order (first = most important) at the first of four
 * offsets around the point that stays inside `bounds` and overlaps neither a
 * label already placed nor any other mark. The first label is always drawn,
 * falling back to its first in-bounds slot; any other label with no free slot
 * is dropped, and the hover tooltip still names it.
 */
export function placeLabels(
  requests: LabelRequest[],
  bounds: { left: number; top: number; right: number; bottom: number },
): PlacedLabel[] {
  const charWidth = 6.4;
  const height = 12;
  const marks = requests.map((r) => ({ id: r.id, box: [r.x - 6, r.y - 6, r.x + 6, r.y + 6] as Box }));
  const placed: { box: Box; label: PlacedLabel }[] = [];
  for (const request of requests) {
    const width = request.text.length * charWidth;
    const candidates: [PlacedLabel["anchor"], number, number, number][] = [
      ["start", request.x + 9, request.y + 4, request.x + 9],
      ["end", request.x - 9, request.y + 4, request.x - 9 - width],
      ["middle", request.x, request.y - 11, request.x - width / 2],
      ["middle", request.x, request.y + 19, request.x - width / 2],
    ];
    const slots = candidates.map(([anchor, lx, ly, left]) => {
      const box: Box = [left, ly - height + 2, left + width, ly + 2];
      const inBounds = box[0] >= bounds.left && box[2] <= bounds.right && box[1] >= bounds.top && box[3] <= bounds.bottom;
      const clear =
        placed.every((other) => !overlaps(box, other.box)) &&
        marks.every((mark) => mark.id === request.id || !overlaps(box, mark.box));
      return { box, inBounds, clear, label: { ...request, anchor, lx, ly } };
    });
    const slot = slots.find((c) => c.inBounds && c.clear) ?? (placed.length === 0 ? slots.find((c) => c.inBounds) : undefined);
    if (slot) placed.push({ box: slot.box, label: slot.label });
  }
  return placed.map(({ label }) => label);
}
