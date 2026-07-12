export type WbsNode = {
  name: string;
  children?: WbsNode[];
};

export type ExtractionDiagnostics = {
  activity_count: number;
  critical_count: number;
  milestone_count: number;
  relationships_parsed: number;
  float_coverage_pct: number;
  date_coverage_pct: number;
  status_breakdown: {
    completed: number;
    in_progress: number;
    not_started: number;
  };
};

export type UploadResponse = {
  schedule_id: string;
  data_date: string;
  activity_count: number;
  wbs_tree: WbsNode[];
  has_baseline: boolean;
  data_quality_warning: string | null;
  diagnostics: ExtractionDiagnostics;
};

export type ReportType = "weekly_oac" | "monthly_executive";

export type NarrativeSections = {
  executive_summary: boolean;
  critical_path_narrative: boolean;
  show_relationship_types: boolean; // only meaningful when critical_path_narrative is on
  milestone_changes: boolean; // requires a P6 Baseline in the uploaded file
  near_critical_discussion: boolean;
  major_schedule_risks: boolean;
  procurement_impacts: boolean;
  owner_talking_points: boolean;
  pm_talking_points: boolean;
};

export type NarrativeRequest = {
  report_type: ReportType;
  lookback_days: number;
  lookahead_days: number;
  wbs_node_names: string[] | null;
  critical_only: boolean;
  milestones_only: boolean;
  include_schedule_metrics: boolean;
  steer: string | null;
  sections: NarrativeSections;
};

export type NarrativeResponse = {
  narrative: string;
  filtered_payload: unknown;
};

export type ApiErrorBody = {
  detail?: string;
};

export type BillingStatus = {
  subscribed: boolean;
  status: string | null;
  trial_narratives_used: number;
  trial_narratives_limit: number;
  trial_remaining: number;
  can_generate: boolean;
};

export type BillingPlan = "monthly" | "annual";
