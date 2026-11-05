/** Criteria scores label (owner feedback on chat 5821ac77): honest, without "not measurements". */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CriteriaScoresBlockSchema, TcoBlockSchema } from "../../lib/protocol";
import { CriteriaScores } from "./CriteriaScores";
import { Tco } from "./Tco";

const block = CriteriaScoresBlockSchema.parse({
  type: "criteria_scores",
  title: "Criteria and scores (0–100, computed from the sourced data)",
  criteria_version: 1,
  criteria: [
    {
      key: "ownership_cost",
      label: "Ownership cost",
      weight: 60,
      definition: "Total cost of owning the car over your period.",
      inputs: ["total ownership cost over the period including depreciation (EUR)", "running costs (EUR/year)"],
    },
    { key: "reliability", label: "Reliability", weight: 40, definition: "Documented issues.", inputs: ["issues"] },
  ],
  cars: [
    {
      car_id: "prado",
      label: "Toyota Land Cruiser Prado",
      ranked: true,
      total: 72,
      coverage: 1,
      parts: {
        ownership_cost: {
          score: 74,
          insufficient: false,
          inputs: ["ownership cost 29406 EUR over 5 years including depreciation (5881 EUR/year)"],
        },
        reliability: { score: null, insufficient: true, inputs: [] },
      },
    },
  ],
  winner_car_id: "prado",
  unmapped_wishes: [],
});

describe("criteria scores label", () => {
  const html = renderToStaticMarkup(<CriteriaScores b={block} />);

  it("says the scores are computed from the sourced data, never 'not measurements'", () => {
    expect(html).toContain("Scores 0–100 computed from the sourced data");
    expect(html).not.toContain("not measurements");
    expect(html).toContain("Criteria and scores");
  });

  it("shows the data each score is built from, per criterion and per car", () => {
    expect(html).toContain("What each score is built from");
    expect(html).toContain("total ownership cost over the period including depreciation (EUR)");
    expect(html).toContain("ownership cost 29406 EUR over 5 years including depreciation");
  });

  it("keeps the insufficient-data state", () => {
    expect(html).toContain("insufficient data");
  });
});

describe("ownership cost block (chat 5821ac77)", () => {
  const tco = TcoBlockSchema.parse({
    type: "tco",
    title: "Ownership cost",
    annual_km: 15000,
    annual_km_assumed: true,
    years: 5,
    cars: [
      {
        car_id: "sorento",
        label: "Kia Sorento",
        condition: "NEW",
        age_years: null,
        annual_total: 1281,
        five_year_total: 31738,
        items: [],
      },
    ],
  });
  const html = renderToStaticMarkup(<Tco b={tco} />);

  it("leads with the total including depreciation and labels the running costs", () => {
    expect(html).toContain("incl. depreciation");
    expect(html).toContain("running costs (without depreciation)");
    expect(html.indexOf("31,738")).toBeLessThan(html.indexOf("1,281"));
  });

  it("says the mileage is assumed", () => {
    expect(html).toContain("km/yr (assumed)");
  });
});
