/** Spec 011 US7 (T122, T123): candidate sources are labelled "unverified source"; "no data" names what was tried. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DataPanelBlockSchema, SourceRefSchema, type BlockOf, type SourceRef } from "../../lib/protocol";
import { SourceItem } from "../badges";
import { DataPanel, triedText } from "../blocks/DataPanel";

const src: SourceRef = {
  name: "Roadster data sheet",
  url: "https://cand-a.example/roadster",
  type: "SPEC_DATABASE",
  retrieved_at: "2026-11-05T10:00:00Z",
};

describe("unverified source label (010 T059)", () => {
  it("labels a candidate source and not a verified one", () => {
    expect(SourceRefSchema.parse({ ...src, unverified: true }).unverified).toBe(true);
    expect(renderToStaticMarkup(<SourceItem s={{ ...src, unverified: true }} />)).toContain("unverified source");
    expect(renderToStaticMarkup(<SourceItem s={src} />)).not.toContain("unverified source");
  });
});

const panel = (tried?: { domain: string; outcome: string; reason?: string | null }[]): BlockOf<"data_panel"> =>
  DataPanelBlockSchema.parse({
    type: "data_panel",
    changed: null,
    cars: [
      {
        car_id: "v1",
        car_key: "car#1",
        label: "Roadster",
        values: 0,
        areas: [{ area: "used_price", status: "UNAVAILABLE", reason: "no usable sources found", findable: false,
                  ...(tried ? { tried } : {}) }],
      },
    ],
  });

describe('"no data" names the sources tried (010 T067)', () => {
  it("formats domains with their outcomes", () => {
    expect(
      triedText([
        { domain: "km77.com", outcome: "empty" },
        { domain: "motor.es", outcome: "robots" },
        { domain: "coches.com", outcome: "rejected", reason: "other_variant" },
      ]),
    ).toBe("km77.com (no value), motor.es (robots), coches.com (rejected: other variant)");
  });

  it("shows the tried line in the area row", () => {
    const html = renderToStaticMarkup(<DataPanel b={panel([{ domain: "nothing.example", outcome: "empty" }])} />);
    expect(html).toContain("Tried: nothing.example (no value)");
  });

  it("shows nothing when the server sent no list", () => {
    expect(renderToStaticMarkup(<DataPanel b={panel()} />)).not.toContain("Tried:");
  });
});
