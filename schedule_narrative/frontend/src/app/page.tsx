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
        sections: filters.sections,
      });
      setResult(res);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Narrative generation failed");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-4xl px-6 py-12">
        <header className="border-b border-rule pb-6 mb-8">
          <h1 className="text-xl font-semibold tracking-tight">Schedule Narrative</h1>
          <p className="text-sm text-ink-muted mt-1">
            Upload a P6 XER or XML export. Generate a weekly OAC or monthly executive narrative grounded strictly in
            the schedule&rsquo;s own data.
          </p>
        </header>

        {!schedule ? (
          <UploadPanel onUpload={handleUpload} uploading={uploading} error={uploadError} />
        ) : (
          <div className="space-y-10">
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <div className="flex items-center gap-3">
                <span className="font-mono text-ink">{schedule.data_date}</span>
                <span className="text-ink-muted">{schedule.activity_count} activities</span>
                <span
                  className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${
                    schedule.has_baseline ? "bg-moss-surface text-moss" : "bg-ochre-surface text-ochre"
                  }`}
                >
                  {schedule.has_baseline ? "Baseline detected" : "No baseline"}
                </span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSchedule(null);
                  setResult(null);
                }}
                className="text-ink-muted hover:text-oxide transition-colors"
              >
                Change schedule
              </button>
            </div>

            {!schedule.has_baseline && (
              <p className="-mt-6 text-xs text-ink-muted">
                No P6 Baseline was found in this file, so the narrative won&rsquo;t include &ldquo;days ahead/behind
                plan&rdquo; variance — only critical-path status. Export a P6 XML with the Project Baseline included
                to unlock variance.
              </p>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
              <div className="md:pr-8 md:border-r border-rule">
                <h2 className="text-xs font-medium uppercase tracking-wider text-ink-muted mb-4">
                  Scope
                  {checkedWbsNames.size === 0 && <span className="normal-case tracking-normal"> &middot; entire schedule</span>}
                </h2>
                <div className="max-h-96 overflow-y-auto">
                  <WbsTree nodes={schedule.wbs_tree} checked={checkedWbsNames} onChange={setCheckedWbsNames} />
                </div>
              </div>

              <div>
                <h2 className="text-xs font-medium uppercase tracking-wider text-ink-muted mb-4">Report</h2>
                <FilterPanel
                  value={filters}
                  onChange={setFilters}
                  onSubmit={handleGenerate}
                  submitting={generating}
                  canSubmit={Boolean(schedule)}
                  hasBaseline={schedule.has_baseline}
                />
                {generateError && <p className="mt-3 text-sm text-oxide">{generateError}</p>}
              </div>
            </div>

            {result && (
              <div className="border-t border-rule pt-8">
                <h2 className="text-xs font-medium uppercase tracking-wider text-ink-muted mb-4">Narrative</h2>
                <NarrativeOutput narrative={result.narrative} filteredPayload={result.filtered_payload} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
