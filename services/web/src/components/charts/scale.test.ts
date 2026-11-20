import { describe, expect, it } from "vitest";

import { leadGeometry } from "../../screens/postgame/leadGeometry";
import { positionAt } from "../../screens/postgame/replayModel";
import { lineGeometry } from "./LineChart";
import { areaPath, extent, interpolate, linear, linePath, nearestIndex, pad, symmetric, ticks } from "./scale";

describe("scales", () => {
  it("maps a domain onto a range, either way up", () => {
    const y = linear([0, 100], [200, 0]);
    expect([y(0), y(50), y(100)]).toEqual([200, 100, 0]);
    expect(linear([5, 5], [0, 10])(5)).toBe(5);
  });

  it("finds extents, symmetric leads and padding", () => {
    expect(extent([3, -2, 9])).toEqual([-2, 9]);
    expect(extent([])).toEqual([0, 0]);
    expect(symmetric([-4000, 2500])).toEqual([-4000, 4000]);
    expect(symmetric([0, 0])).toEqual([-1, 1]);
    expect(pad([100, 200], 0.1)).toEqual([90, 210]);
    expect(pad([5, 5])).toEqual([-5, 15]);
  });

  it("picks round ticks", () => {
    expect(ticks(0, 100, 5)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(ticks(1402, 1512, 4)).toEqual([1450, 1500]);
  });

  it("draws lines and areas to one decimal", () => {
    expect(linePath([[0, 10], [5.55, 20]])).toBe("M0,10 L5.6,20");
    expect(areaPath([[0, 10], [10, 30]], 20)).toBe("M0,20 L0,10 L10,30 L10,20 Z");
    expect(linePath([])).toBe("");
    expect(areaPath([], 0)).toBe("");
  });

  it("finds the nearest sample and interpolates between them", () => {
    expect(nearestIndex([0, 60, 120], 70)).toBe(1);
    expect(nearestIndex([0, 60, 120], 100)).toBe(2);
    expect(interpolate([0, 60], [0, 600], 30)).toBe(300);
    expect(interpolate([0, 60], [0, 600], 90)).toBe(600);
    expect(interpolate([0, 60], [10, 600], -5)).toBe(10);
  });
});

describe("chart geometry", () => {
  it("puts zero mid-chart and the biggest lead at the edge", () => {
    const g = leadGeometry([0, 60, 120], [0, 3000, -6000], 120);
    expect(g.top).toBe(6000);
    expect(g.y(0)).toBe(150);
    expect(g.y(-6000)).toBe(300);
    expect(g.x(120)).toBeCloseTo(1000);
    expect(g.line.startsWith("M0,150")).toBe(true);
  });

  it("marks every five minutes", () => {
    expect(leadGeometry([0, 1872], [0, 0], 1872).grid.map((m) => m.t)).toEqual([300, 600, 900, 1200, 1500, 1800]);
  });

  it("ends the rating line on its last point", () => {
    const { last } = lineGeometry([
      { x: 0, y: 1400 },
      { x: 1, y: 1500 },
    ]);
    expect(last?.[0]).toBeCloseTo(990);
    expect(last?.[1]).toBeLessThan(120);
  });
});

describe("replay positions", () => {
  const path = [0, 0, 100, 200, 300, 400];

  it("glides between samples", () => {
    expect(positionAt(path, 10, 5, true)).toEqual({ x: 50, y: 100 });
  });

  it("steps on the sample with reduced motion", () => {
    expect(positionAt(path, 10, 15, false)).toEqual({ x: 100, y: 200 });
  });

  it("holds the last sample, and has nothing without samples", () => {
    expect(positionAt(path, 10, 999, true)).toEqual({ x: 300, y: 400 });
    expect(positionAt([], 10, 5, true)).toBeNull();
  });
});
