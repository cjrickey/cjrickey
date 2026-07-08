"use client";

import { useState } from "react";
import { UploadPanel } from "@/components/UploadPanel";
import { WbsTree } from "@/components/WbsTree";
import { FilterPanel, DEFAULT_FILTER_STATE, type FilterState } from "@/components/FilterPanel";
import { NarrativeOutput } from "@/components/NarrativeOutput";
import { generateNarrative, uploadSchedule } from "@/lib/api";
import type { NarrativeResponse, UploadResponse } from "@/lib/types";

export default function Home() {
  const [schedule, setSchedule] = useState<UploadResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [checkedWbsNames, setCheckedWbsNames] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTER_STATE);

  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [result, setResult] = useState<NarrativeResponse | null>(null);

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      const res = await uploadSchedule(file);
      setSchedule(res);
      setCheckedWbsNames(new Set());
      setResult(null);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleGenerate() {
    if (!schedule) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      const maxFloatDays = filters.maxFloatDays.trim() === "" ? null : Number(filters.maxFloatDays);
      const lookbackDays = filters.lookbackDays.trim() === "" ? 7 : Number(filters.lookbackDays);
      const lookaheadDays = filters.lookaheadDays.trim() === "" ? 7 : Number(filters.lookaheadDays);
      const res = await generateNarrative(schedule.schedule_id, {
        report_type: filters.reportType,
        lookback_days: lookbackDays,
        lookahead_days: lookaheadDays,
        wbs_node_names: checkedWbsNames.size > 0 ? Array.from(checkedWbsNames) : null,
        critical_only: filters.criticalOnly,
        milestones_only: filters.milestonesOnly,
        max_float_days: maxFloatDays,
        include_schedule_metrics: filters.includeScheduleMetrics,
        steer: filters.steer.trim() === "" ? null : filters.steer.trim(),
      });
      setResult(res);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Narrative generation failed");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-50">Schedule Narrative Generator</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Upload a P6 XER or XML export and generate a grounded weekly OAC or monthly executive narrative.
          </p>
        </header>

        {!schedule ? (
          <UploadPanel onUpload={handleUpload} uploading={uploading} error={uploadError} />
        ) : (
          <div className="space-y-6">
            <div className="flex items-center justify-between rounded-md bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="text-sm text-gray-600 dark:text-gray-300">
                Data date <span className="font-medium text-gray-900 dark:text-gray-100">{schedule.data_date}</span>{" "}
                &middot; {schedule.activity_count} activities
              </div>
              <button
                type="button"
                onClick={() => {
                  setSchedule(null);
                  setResult(null);
                }}
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                Upload a different schedule
              </button>
            </div>

            <div
              className={`rounded-md border px-4 py-3 text-sm ${
                schedule.has_baseline
                  ? "border-green-200 dark:border-green-900 bg-green-50 dark:bg-green-950 text-green-800 dark:text-green-200"
                  : "border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950 text-amber-800 dark:text-amber-200"
              }`}
            >
              {schedule.has_baseline
                ? "Project Baseline detected. Variance (days ahead/behind) will be included in the narrative."
                : "No P6 Baseline found in this file. The narrative will describe activities and critical-path status, but will not include “days ahead/behind plan” variance — export a P6 XML with the Project Baseline included to unlock that."}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="rounded-md bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4">
                <h2 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                  WBS scope {checkedWbsNames.size === 0 && <span className="text-gray-400">(none selected = entire schedule)</span>}
                </h2>
                <div className="max-h-96 overflow-y-auto">
                  <WbsTree nodes={schedule.wbs_tree} checked={checkedWbsNames} onChange={setCheckedWbsNames} />
                </div>
              </div>

              <div className="rounded-md bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4">
                <FilterPanel
                  value={filters}
                  onChange={setFilters}
                  onSubmit={handleGenerate}
                  submitting={generating}
                  canSubmit={Boolean(schedule)}
                />
                {generateError && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{generateError}</p>}
              </div>
            </div>

            {result && (
              <div>
                <h2 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Narrative</h2>
                <NarrativeOutput narrative={result.narrative} filteredPayload={result.filtered_payload} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
