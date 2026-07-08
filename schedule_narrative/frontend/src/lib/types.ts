export type WbsNode = {
  name: string;
  children?: WbsNode[];
};

export type UploadResponse = {
  schedule_id: string;
  data_date: string;
  activity_count: number;
  wbs_tree: WbsNode[];
  has_baseline: boolean;
};

export type ReportType = "weekly_oac" | "monthly_executive";

export type NarrativeRequest = {
  report_type: ReportType;
  lookback_days: number;
  lookahead_days: number;
  wbs_node_names: string[] | null;
  critical_only: boolean;
  milestones_only: boolean;
  max_float_days: number | null;
  include_schedule_metrics: boolean;
  steer: string | null;
};

export type NarrativeResponse = {
  narrative: string;
  filtered_payload: unknown;
};

export type ApiErrorBody = {
  detail?: string;
};
