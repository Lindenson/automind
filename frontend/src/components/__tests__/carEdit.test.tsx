/** Spec 010 US10 (T091–T096): what was understood stays visible, and correcting it is cheap and structured. */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  CaseFileMsgSchema,
  VerdictBlockSchema,
  parseBlocks,
  parseServerMsg,
  type ClientMsg,
} from "../../lib/protocol";
import { useCasePanel, watchCase } from "../../store/case";
import { challengeKey, noteworthy, useChat } from "../../store/chat";
import { CarChange, choiceFields } from "../CarChange";
import { CarRow } from "../CasePanel/CasePanel";
import { ChallengeButton, ChallengeControl, ChallengedCell, challengeText } from "../ChallengeButton";
import { IntakeCard, typedEdit } from "../IntakeCard";
import { Message } from "../Message";
import { ConfidenceDot } from "../badges";
import { DataPanel } from "../blocks/DataPanel";
import { SpecLegend } from "../blocks/SpecTable";

let sent: ClientMsg[] = [];
beforeEach(() => {
  useChat.getState().newChat();
  sent = [];
  useChat.getState().setTransport({ send: (m) => (sent.push(m), true), close: () => undefined });
  useCasePanel.setState({ open: false, unseen: 0, focus: null });
});
afterEach(() => useChat.getState().setTransport(null));

const options = { generation: ["KH7"], engine: ["1.5 TSI 150 CV"], gearbox: ["dct"], trim: [] };
const caseCar = {
  key: "car#1",
  request_text: "SEAT Ateca",
  condition: "NEW",
  variant_id: "v1",
  label: "SEAT Ateca KH7 1.0 TSI 110 CV Style",
  resolution: "PROPOSED",
  variant_label: "1.0 TSI 110 CV · manual · Style · 2016–",
  options,
};
const caseMsg = (version: number, changes: string[], turn = "t1") => ({
  type: "case_file",
  seq: version,
  turn_id: turn,
  version,
  case: { cars: [caseCar] },
  changes,
});

describe("structured car edit (FR-037)", () => {
  it("parses the version line and the options of a case car", () => {
    const m = CaseFileMsgSchema.parse(caseMsg(1, []));
    expect(m.case.cars[0]).toMatchObject({ variant_label: caseCar.variant_label, options });
  });

  it("sends car_edit and shows the turn as an edit", () => {
    useChat.setState({ confirm: { type: "confirm_request", kind: "intake", text: "", options: [] } as never });
    expect(useChat.getState().carEdit("car#1", "engine", " 1.5 TSI 150 CV ")).toBe(true);
    expect(sent).toEqual([
      expect.objectContaining({ type: "car_edit", car_key: "car#1", field: "engine", value: "1.5 TSI 150 CV" }),
    ]);
    expect(useChat.getState().pending?.kind).toBe("edit");
    expect(useChat.getState().confirm).toBeNull();
    // busy: a second edit is refused
    expect(useChat.getState().carEdit("car#1", "remove")).toBe(false);
  });

  it("offers the options, Not this car and Remove", () => {
    expect(choiceFields(options)).toEqual(["generation", "engine", "gearbox"]);
    const html = renderToStaticMarkup(<CarChange car={caseCar as never} name="Ateca" open onOpenChange={() => {}} />);
    expect(html).toContain("1.5 TSI 150 CV");
    expect(html).toContain("KH7");
    expect(html).toContain("Not this car");
    expect(html).toContain("Remove");
    expect(html).not.toContain(">Trim<"); // no options for the trim: no chips
  });

  it("shows the version line in the case panel and makes the PROPOSED badge a button", () => {
    const car = CaseFileMsgSchema.parse(caseMsg(1, [])).case.cars[0]!;
    const html = renderToStaticMarkup(<CarRow car={car} />);
    expect(html).toContain(caseCar.variant_label);
    expect(html).toMatch(/<button[^>]*aria-expanded="false"[^>]*>to confirm<\/button>/);
    expect(html).toContain("Change");
  });

  it("gives intake fields without chips an inline edit", () => {
    expect(typedEdit({ field: "year", value: "2019", basis: "STATED" }, "car#1")).toBe(true);
    expect(typedEdit({ field: "gearbox", value: "DSG", basis: "STATED", options: ["DSG", "Manual"] }, "car#1")).toBe(false);
    const html = renderToStaticMarkup(
      <IntakeCard
        req={{ type: "confirm_request", kind: "intake", text: "Check", options: [] } as never}
        card={{ cars: [{ key: "car#1", display_name: "Golf", items: [{ field: "year", value: "2019", basis: "STATED" }] }], profile: [] } as never}
      />,
    );
    expect(html).toContain('aria-label="Edit');
  });
});

describe("Agreed entry and version line (FR-035, FR-036, FR-039)", () => {
  const agreed = {
    type: "agreed",
    seq: 3,
    turn_id: "t1",
    message_id: "a1",
    created_at: "2026-11-05T10:00:00Z",
    text: "Agreed: SEAT Ateca (1.0 TSI 110 CV · manual)",
    blocks: [{ type: "agreed", cars: [{ key: "car#1", label: "SEAT Ateca", variant_label: "1.0 TSI 110 CV · manual", basis: "STATED" }] }],
  };

  it("keeps the turn running and renders a collapsed Agreed entry", () => {
    useChat.setState({ pending: { userMessageId: "", startedAt: 0, statuses: [] } });
    useChat.getState().handleRaw(agreed);
    useChat.getState().handleRaw(agreed); // replayed: once
    const s = useChat.getState();
    expect(s.pending).not.toBeNull();
    expect(s.messages).toHaveLength(1);
    const html = renderToStaticMarkup(<Message m={s.messages[0]!} />);
    expect(html).toContain("<details");
    expect(html).toContain("Agreed");
    expect(html).toContain("1.0 TSI 110 CV · manual");
    expect(html).not.toContain('role="group"'); // no rating on it
  });

  it("puts Based on above the verdict, with the versions under the headline", () => {
    const verdict = VerdictBlockSchema.parse({
      type: "verdict", headline: "SEAT Ateca", pick_car_id: "v1", tie: false, confidence: "HIGH", confidence_reason: "ok",
    });
    const blocks = parseBlocks([
      verdict,
      { type: "case_summary", persona: "BUYER", facts: ["budget €30 000"],
        cars: [{ key: "car#1", label: "SEAT Ateca", condition: "NEW", year: null, variant_label: "1.0 TSI · manual" }] },
    ]);
    const html = renderToStaticMarkup(
      <Message m={{ role: "assistant", message_id: "r1", created_at: "", text: "Report", blocks }} />,
    );
    const based = html.indexOf('data-testid="based-on"');
    expect(based).toBeGreaterThan(-1);
    expect(based).toBeLessThan(html.indexOf('aria-label="Verdict"'));
    expect(html).toContain("for: SEAT Ateca (1.0 TSI · manual)");
    expect(html.match(/What I understood/g)).toBeNull(); // the summary became the strip
  });
});

describe("the case panel speaks up (FR-038)", () => {
  it("leaves one Noted entry per turn and skips the intake bookkeeping", () => {
    expect(noteworthy(["asked: ENGINE", "confirmation card shown", "budget €40 000"])).toEqual(["budget €40 000"]);
    const { handleRaw } = useChat.getState();
    handleRaw(caseMsg(1, ["car#1 added: SEAT Ateca"]));
    handleRaw(caseMsg(2, ["asked: ENGINE"]));
    handleRaw(caseMsg(3, ["budget €40 000"]));
    handleRaw(caseMsg(4, ["usage: mountains"], "t2"));
    const notes = useChat.getState().messages.filter((m) => m.role === "note");
    expect(notes).toHaveLength(2);
    expect(notes[0]).toMatchObject({ changes: ["car#1 added: SEAT Ateca", "budget €40 000"] });
    const html = renderToStaticMarkup(<Message m={notes[0]!} />);
    expect(html).toContain("Noted:");
    expect(html).toContain(">Edit</button>");
  });

  it("opens on wide screens on the first case file and counts unseen changes when closed", () => {
    let stop = watchCase(() => true);
    useChat.getState().handleRaw(caseMsg(1, ["car#1 added: SEAT Ateca"]));
    expect(useCasePanel.getState().open).toBe(true);
    stop();

    useChat.getState().newChat();
    useCasePanel.setState({ open: false, unseen: 0 });
    stop = watchCase(() => false);
    useChat.getState().handleRaw(caseMsg(1, ["car#1 added: SEAT Ateca"]));
    useChat.getState().handleRaw(caseMsg(2, ["budget €40 000"]));
    expect(useCasePanel.getState().open).toBe(false);
    expect(useCasePanel.getState().unseen).toBe(2);
    useCasePanel.getState().setOpen(true);
    expect(useCasePanel.getState().unseen).toBe(0);
    stop();
  });
});

describe("legible data quality (FR-040)", () => {
  it("shows confidence as text and a legend above the table", () => {
    expect(renderToStaticMarkup(<ConfidenceDot c="LOW" />)).toContain(">low<");
    const legend = renderToStaticMarkup(<SpecLegend />);
    expect(legend).toContain("Legend:");
    expect(legend).toContain("confidence");
  });

  it("puts reasons behind a button, not a title", () => {
    const html = renderToStaticMarkup(
      <DataPanel
        b={{
          type: "data_panel",
          changed: null,
          cars: [{ car_id: "v1", car_key: "car#1", label: "Ateca", values: 3,
                   areas: [{ area: "reliability", status: "MISSING", reason: "no owner survey found", findable: false }] }],
        }}
      />,
    );
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("title=");
  });
});

describe('"wrong?" with a reason and the result in the cell (FR-041)', () => {
  it("sends the reason as the text and shows checking", () => {
    expect(challengeText("wrong for this version", " it is the 1.5 ")).toBe("wrong for this version: it is the 1.5");
    useChat.getState().challenge("v1", "zero_100", "outdated");
    expect(sent.at(-1)).toMatchObject({ type: "challenge", car_id: "v1", attribute: "zero_100", text: "outdated" });
    expect(useChat.getState().challenges[challengeKey("v1", "zero_100")]).toBe("checking");
    const state = useChat.getState().challenges[challengeKey("v1", "zero_100")];
    expect(renderToStaticMarkup(<ChallengeControl state={state} label="0–100 km/h" onSend={() => {}} />)).toContain("checking…");
  });

  it("stores the result by car and attribute and renders it in the cell", () => {
    useChat.getState().challenge("v1", "zero_100", "wrong value");
    const before = useChat.getState().messages.length;
    const r = parseServerMsg({
      type: "challenge_result", outcome: "CORRECTED", attribute: "zero_100", car_id: "v1", before: "5.4 s", after: "5.9 s",
    });
    useChat.getState().handleRaw(r);
    expect(useChat.getState().messages.length).toBe(before); // no bubble: the cell shows it
    const result = useChat.getState().challenges[challengeKey("v1", "zero_100")];
    expect(result).toMatchObject({ outcome: "CORRECTED" });
    const html = renderToStaticMarkup(
      <ChallengedCell result={result}>
        <span>5.4 s</span>
      </ChallengedCell>,
    );
    expect(html).toContain("<s");
    expect(html).toContain("5.9 s");
    expect(html).toContain("re-checked");
    // the button is gone ("checking…" is reset)
    expect(renderToStaticMarkup(<ChallengeControl state={result} label="x" onSend={() => {}} />)).toBe("");
  });

  it("names the row by its label", () => {
    const html = renderToStaticMarkup(<ChallengeButton carId="v2" attribute="zero_100" label="0–100 km/h" />);
    expect(html).toContain('aria-label="This is wrong: 0–100 km/h"');
  });
});
