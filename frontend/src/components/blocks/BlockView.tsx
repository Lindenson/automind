import type { Block } from "../../lib/protocol";
import { CaseSummary } from "./CaseSummary";
import { CriteriaScores } from "./CriteriaScores";
import { Engineering } from "./Engineering";
import { Maintenance } from "./Maintenance";
import { Manufacturer } from "./Manufacturer";
import { MetricBars } from "./MetricBars";
import { Notice } from "./Notice";
import { ProfileScores } from "./ProfileScores";
import { RaceChart } from "./RaceChart";
import { Reliability } from "./Reliability";
import { Reviews } from "./Reviews";
import { Sources } from "./Sources";
import { Tco } from "./Tco";
import { Feasibility } from "./Feasibility";
import { SpecTable } from "./SpecTable";
import { QuickReplies } from "./QuickReplies";

export function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "spec_table":
      return <SpecTable b={block} />;
    case "metric_bars":
      return <MetricBars b={block} />;
    case "race_chart":
      return <RaceChart b={block} />;
    case "profile_scores":
      return <ProfileScores b={block} />;
    case "maintenance":
      return <Maintenance b={block} />;
    case "sources":
      return <Sources b={block} />;
    case "notice":
      return <Notice b={block} />;
    case "case_summary":
      return <CaseSummary b={block} />;
    case "criteria_scores":
      return <CriteriaScores b={block} />;
    case "engineering":
      return <Engineering b={block} />;
    case "manufacturer":
      return <Manufacturer b={block} />;
    case "tco":
      return <Tco b={block} />;
    case "feasibility":
      return <Feasibility b={block} />;
    case "reliability":
      return <Reliability b={block} />;
    case "reviews":
      return <Reviews b={block} />;
    case "quick_replies":
      return <QuickReplies b={block} />;
    default:
      return null;
  }
}
