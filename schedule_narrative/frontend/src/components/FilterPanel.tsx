"use client";

import type { ReportType } from "@/lib/types";

export type FilterState = {
  reportType: ReportType;
  lookbackDays: number;
  lookaheadDays: number;
  criticalOnly: boolean;
  milestonesOnly: boolean;
  maxFloatDays: string; // kept as string so the input can be legitimately empty
  includeScheduleMetrics: boolean;
  steer: string;
};

export const DEFAULT_FILTER_STATE: FilterState = {
  reportType: "weekly_oac",
  lookbackDays: 7,
  lookaheadDays: 7,
  criticalOnly: false,
  milestonesOnly: false,
  maxFloatDays: "",
  includeScheduleMetrics: true,
  steer: "",
};

type FilterPanelProps = {
  value: FilterState;
  onChange: (next: FilterState) => void;
  onSubmit: () => void;
  submitting: boolean;
  canSubmit: boolean;
};

export function FilterPanel({ value, onChange, onSubmit, submitting, canSubmit }: FilterPanelProps) {
  function set<K extends keyof FilterState>(key: K, next: FilterState[K]) {
    onChange({ ...value, [key]: next });
  }

  return (
    <div className="space-y-5">
      <div>
        <span className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Report type</span>
        <div className="flex gap-2">
          {(
            [
              ["weekly_oac", "Weekly OAC"],
              ["monthly_executive", "Monthly Executive"],
            ] as const
          ).map(([type, label]) => (
            <button
              key={type}
              type="button"
              onClick={() => set("reportType", type)}
              className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                value.reportType === type
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 border-gray-300 dark:border-gray-600"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {value.reportType === "weekly_oac" && (
        <div className="flex gap-4">
          <label className="flex-1 text-sm">
            <span className="block text-gray-700 dark:text-gray-300 mb-1">Lookback days</span>
            <input
              type="number"
              min={0}
              value={value.lookbackDays}
              onChange={(e) => set("lookbackDays", Number(e.target.value))}
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5"
            />
          </label>
          <label className="flex-1 text-sm">
            <span className="block text-gray-700 dark:text-gray-300 mb-1">Lookahead days</span>
            <input
              type="number"
              min={0}
              value={value.lookaheadDays}
              onChange={(e) => set("lookaheadDays", Number(e.target.value))}
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5"
            />
          </label>
        </div>
      )}

      <label className="text-sm block">
        <span className="block text-gray-700 dark:text-gray-300 mb-1">Max float days (optional)</span>
        <input
          type="number"
          value={value.maxFloatDays}
          onChange={(e) => set("maxFloatDays", e.target.value)}
          placeholder="No limit"
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5"
        />
      </label>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
          <input
            type="checkbox"
            checked={value.criticalOnly}
            onChange={(e) => set("criticalOnly", e.target.checked)}
            className="h-4 w-4 rounded border-gray-400 accent-blue-600"
          />
          Critical activities only
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
          <input
            type="checkbox"
            checked={value.milestonesOnly}
            onChange={(e) => set("milestonesOnly", e.target.checked)}
            className="h-4 w-4 rounded border-gray-400 accent-blue-600"
          />
          Milestones only
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
          <input
            type="checkbox"
            checked={value.includeScheduleMetrics}
            onChange={(e) => set("includeScheduleMetrics", e.target.checked)}
            className="h-4 w-4 rounded border-gray-400 accent-blue-600"
          />
          Include schedule metrics (variance, float, critical path)
        </label>
      </div>

      <label className="text-sm block">
        <span className="block text-gray-700 dark:text-gray-300 mb-1">Steering note (optional)</span>
        <textarea
          value={value.steer}
          onChange={(e) => set("steer", e.target.value)}
          rows={2}
          placeholder="e.g. emphasize the exterior envelope work"
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5"
        />
      </label>

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canSubmit || submitting}
        className="w-full rounded-md bg-blue-600 text-white py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
      >
        {submitting ? "Generating…" : "Generate narrative"}
      </button>
    </div>
  );
}
