import { createContext, useCallback, useContext } from "react";
import type { Block } from "../lib/protocol";
import { CAR_COLORS } from "../lib/util";

/** Maps car_id -> colour, consistent across all blocks of one message. */
export const CarColorContext = createContext<Map<string, string>>(new Map());

export function buildCarColors(blocks: Block[]): Map<string, string> {
  const ids: string[] = [];
  const add = (id: string) => {
    if (!ids.includes(id)) ids.push(id);
  };
  for (const b of blocks) {
    switch (b.type) {
      case "spec_table":
        b.cars.forEach((c) => add(c.id));
        break;
      case "metric_bars":
        b.metrics.forEach((m) => m.values.forEach((v) => add(v.car_id)));
        break;
      case "race_chart":
        b.series.forEach((s) => add(s.car_id));
        b.results.forEach((r) => add(r.car_id));
        break;
      case "profile_scores":
        b.scores.forEach((s) => add(s.car_id));
        break;
      case "maintenance":
        b.items.forEach((i) => add(i.car_id));
        break;
      case "criteria_scores":
      case "engineering":
      case "tco":
      case "reliability":
      case "reviews":
        b.cars.forEach((c) => add(c.car_id));
        break;
      default:
        break;
    }
  }
  return new Map(ids.map((id, i) => [id, CAR_COLORS[i % CAR_COLORS.length]!]));
}

export function useCarColor(): (carId: string) => string {
  const map = useContext(CarColorContext);
  return useCallback((id: string) => map.get(id) ?? CAR_COLORS[0], [map]);
}
