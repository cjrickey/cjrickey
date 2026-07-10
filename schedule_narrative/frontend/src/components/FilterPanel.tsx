"use client";

import type { NarrativeSections, ReportType } from "@/lib/types";

export type FilterState = {
  reportType: ReportType;
  lookbackDays: string; // kept as string, like maxFloatDays -- a number-typed
  lookaheadDays: string; // controlled input re-renders with a stale/padded
  criticalOnly: boolean; // string on certain edit sequences (e.g. clearing
  milestonesOnly: boolean; // then typing a digit shows "09" instead of "9")
  maxFloatDays: string; // kept as string so the input can be legitimately empty
  includeScheduleMetrics: boolean;
  steer: string;
  sections: NarrativeSections;
};

const DEFAULT_SECTIONS: NarrativeSections = {
  executive_summary: false,
  critical_path_narrative: false,
  show_relationship_types: true,
  milestone_changes: false,
  near_critical_discussion: false,
  major_schedule_risks: false,
  procurement_impacts: false,
  owner_talking_points: false,
  pm_talking_points: false,
};

export const DEFAULT_FILTER_STATE: FilterState = {
  reportType: "weekly_oac",
  lookbackDays: "7",
  lookaheadDays: "7",
  criticalOnly: false,
  milestonesOnly: false,
  maxFloatDays: "",
  includeScheduleMetrics: true,
  steer: "",
  sections: DEFAULT_SECTIONS,
};

// Each report type's own sensible default date range -- applied when the
// user switches to that type, so monthly keeps its existing ~30-day
// default instead of inheriting whatever weekly happened to be set to.
const REPORT_TYPE_DATE_DEFAULTS: Record<ReportType, { lookbackDays: string; lookaheadDays: string }> = {
  weekly_oac: { lookbackDays: "7", lookaheadDays: "7" },
  monthly_executive: { lookbackDays: "30", lookaheadDays: "30" },
};

const SECTION_OPTIONS: { key: keyof NarrativeSections; label: string; requiresBaseline?: boolean }[] = [
  { key: "executive_summary", label: "Executive summary" },
  { key: "critical_path_narrative", label: "Critical path narrative" },
  { key: "milestone_changes", label: "Milestone changes", requiresBaseline: true },
  { key: "near_critical_discussion", label: "Near-critical path discussion" },
  { key: "major_schedule_risks", label: "Major schedule risks" },
  { key: "procurement_impacts", label: "Procurement" },
  { key: "owner_talking_points", label: "Three owner talking points" },
  { key: "pm_talking_points", label: "Three PM talking points" },
];

const inputClasses =
  "w-full rounded-sm border border-rule bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-oxide outline-none transition-colors";

type FilterPanelProps = {
  value: FilterState;
  onChange: (next: FilterState) => void;
  onSubmit: () => void;
  submitting: boolean;
  canSubmit: boolean;
  hasBaseline: boolean;
};

export function FilterPanel({ value, onChange, onSubmit, submitting, canSubmit, hasBaseline }: FilterPanelProps) {
  function set<K extends keyof FilterState>(key: K, next: FilterState[K]) {
    onChange({ ...value, [key]: next });
  }

  function setSection(key: keyof NarrativeSections, checked: boolean) {
    onChange({ ...value, sections: { ...value.sections, [key]: checked } });
  }

  return (
    <div className="space-y-6">
      <div>
        <span className="block text-xs uppercase tracking-wide text-ink-muted mb-2">Report type</span>
        <div className="flex gap-1 rounded-sm border border-rule p-0.5 w-fit">
          {(
            [
              ["weekly_oac", "Weekly OAC"],
              ["monthly_executive", "Monthly Executive"],
            ] as const
          ).map(([type, label]) => (
            <button
              key={type}
              type="button"
              onClick={() => onChange({ ...value, reportType: type, ...REPORT_TYPE_DATE_DEFAULTS[type] })}
              className={`px-3 py-1 rounded-sm text-sm transition-colors ${
                value.reportType === type ? "bg-oxide text-white" : "text-ink-muted hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-4">
        <label className="flex-1 text-sm">
          <span className="block text-xs uppercase tracking-wide text-ink-muted mb-2">Lookback days</span>
          <input
            type="number"
            min={0}
            value={value.lookbackDays}
            onChange={(e) => set("lookbackDays", e.target.value)}
            className={`${inputClasses} font-mono`}
          />
        </label>
        <label className="flex-1 text-sm">
          <span className="block text-xs uppercase tracking-wide text-ink-muted mb-2">Lookahead days</span>
          <input
            type="number"
            min={0}
            value={value.lookaheadDays}
            onChange={(e) => set("lookaheadDays", e.target.value)}
            className={`${inputClasses} font-mono`}
          />
        </label>
      </div>

      <label className="text-sm block">
        <span className="block text-xs uppercase tracking-wide text-ink-muted mb-2">Max float days (optional)</span>
        <input
          type="number"
          value={value.maxFloatDays}
          onChange={(e) => set("maxFloatDays", e.target.value)}
          placeholder="No limit"
          className={`${inputClasses} font-mono`}
        />
      </label>

      <div className="space-y-2.5">
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={value.criticalOnly}
            onChange={(e) => set("criticalOnly", e.target.checked)}
            className="h-4 w-4 rounded-sm border-rule accent-oxide"
          />
          Critical activities only
        </label>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={value.milestonesOnly}
            onChange={(e) => set("milestonesOnly", e.target.checked)}
            className="h-4 w-4 rounded-sm border-rule accent-oxide"
          />
          Milestones only
        </label>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={value.includeScheduleMetrics}
            onChange={(e) => set("includeScheduleMetrics", e.target.checked)}
            className="h-4 w-4 rounded-sm border-rule accent-oxide"
          />
          Include schedule metrics (variance, float, critical path)
        </label>
      </div>

      <div>
        <span className="block text-xs uppercase tracking-wide text-ink-muted mb-2">Additional sections</span>
        <div className="space-y-2">
          {SECTION_OPTIONS.map(({ key, label, requiresBaseline }) => {
            const disabled = requiresBaseline && !hasBaseline;
            return (
              <div key={key}>
                <label
                  className={`flex items-center gap-2 text-sm ${disabled ? "text-ink-muted/50" : "text-ink"}`}
                  title={disabled ? "Requires a P6 Baseline embedded in the uploaded file" : undefined}
                >
                  <input
                    type="checkbox"
                    checked={value.sections[key]}
                    disabled={disabled}
                    onChange={(e) => setSection(key, e.target.checked)}
                    className="h-4 w-4 rounded-sm border-rule accent-oxide disabled:opacity-40"
                  />
                  {label}
                  {requiresBaseline && <span className="text-xs text-ink-muted">requires baseline</span>}
                </label>
                {key === "critical_path_narrative" && value.sections.critical_path_narrative && (
                  <label className="flex items-center gap-2 text-sm text-ink-muted ml-6 mt-1.5">
                    <input
                      type="checkbox"
                      checked={value.sections.show_relationship_types}
                      onChange={(e) => setSection("show_relationship_types", e.target.checked)}
                      className="h-4 w-4 rounded-sm border-rule accent-oxide"
                    />
                    Name the relationship type (e.g. &ldquo;start to start&rdquo;) -- off just says
                    &ldquo;next&rdquo;/&ldquo;alongside&rdquo;
                  </label>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <label className="text-sm block">
        <span className="block text-xs uppercase tracking-wide text-ink-muted mb-2">Steering note (optional)</span>
        <textarea
          value={value.steer}
          onChange={(e) => set("steer", e.target.value)}
          rows={2}
          placeholder="e.g. emphasize the exterior envelope work"
          className={inputClasses}
        />
      </label>

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canSubmit || submitting}
        className="w-full rounded-sm bg-oxide text-white py-2 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition-all"
      >
        {submitting ? "Generating…" : "Generate narrative"}
      </button>
    </div>
  );
}
