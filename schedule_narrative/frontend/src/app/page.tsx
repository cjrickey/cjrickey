"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@clerk/nextjs";
import { UploadPanel } from "@/components/UploadPanel";
import { WbsTree } from "@/components/WbsTree";
import { FilterPanel, DEFAULT_FILTER_STATE, type FilterState } from "@/components/FilterPanel";
import { NarrativeOutput } from "@/components/NarrativeOutput";
import { SubscriptionGate } from "@/components/SubscriptionGate";
import { useBilling } from "@/lib/BillingContext";
import { createPortalSession, generateNarrative, uploadSchedule } from "@/lib/api";
import type { NarrativeResponse, UploadResponse } from "@/lib/types";

export default function Home() {
  return (
    <SubscriptionGate>
      <ScheduleNarrativeApp />
    </SubscriptionGate>
  );
}

function ScheduleNarrativeApp() {
  const { getToken } = useAuth();
  const { status: billing, refresh: refreshBilling } = useBilling();
  const [schedule, setSchedule] = useState<UploadResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [checkedWbsNames, setCheckedWbsNames] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTER_STATE);

  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [result, setResult] = useState<NarrativeResponse | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      const res = await uploadSchedule(file, token);
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
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      const lookbackDays = filters.lookbackDays.trim() === "" ? 7 : Number(filters.lookbackDays);
      const lookaheadDays = filters.lookaheadDays.trim() === "" ? 7 : Number(filters.lookaheadDays);
      const res = await generateNarrative(
        schedule.schedule_id,
        {
          report_type: filters.reportType,
          lookback_days: lookbackDays,
          lookahead_days: lookaheadDays,
          wbs_node_names: checkedWbsNames.size > 0 ? Array.from(checkedWbsNames) : null,
          critical_only: filters.criticalOnly,
          milestones_only: filters.milestonesOnly,
          include_schedule_metrics: filters.includeScheduleMetrics,
          steer: filters.steer.trim() === "" ? null : filters.steer.trim(),
          sections: filters.sections,
        },
        token,
      );
      setResult(res);
      await refreshBilling();
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Narrative generation failed");
    } finally {
      setGenerating(false);
    }
  }

  async function handleManageBilling() {
    setBillingError(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      const { portal_url } = await createPortalSession(token);
      window.location.href = portal_url;
    } catch (err) {
      setBillingError(err instanceof Error ? err.message : "Couldn't open billing portal");
    }
  }

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-4xl px-6 py-12">
        <header className="border-b border-rule pb-6 mb-8 flex items-start justify-between gap-6">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Schedule Narrative Generator</h1>
            <p className="text-sm text-ink-muted mt-1">
              Upload a P6 XER or XML export. Generate a weekly OAC or monthly executive narrative grounded strictly in
              the schedule&rsquo;s own data.
            </p>
          </div>
          <div className="flex items-center gap-4 shrink-0">
            {billing.status === "admin" ? (
              <span className="text-sm text-ink-muted">Admin access</span>
            ) : billing.subscribed ? (
              <button
                type="button"
                onClick={handleManageBilling}
                className="text-sm text-ink-muted hover:text-oxide transition-colors"
              >
                Manage billing
              </button>
            ) : (
              <span className="flex items-center gap-3 text-sm">
                <span className="text-ink-muted">
                  Free trial &middot; {billing.trial_remaining} of {billing.trial_narratives_limit} left
                </span>
                <Link href="/pricing" className="text-oxide hover:brightness-110 transition-all">
                  Upgrade
                </Link>
              </span>
            )}
            <UserButton />
          </div>
        </header>

        {billingError && <p className="-mt-4 mb-8 text-sm text-oxide">{billingError}</p>}

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

            {schedule.data_quality_warning && (
              <p className="-mt-6 text-xs text-ochre">{schedule.data_quality_warning}</p>
            )}

            <details className="-mt-6 text-xs text-ink-muted">
              <summary className="cursor-pointer select-none hover:text-ink">Extraction details</summary>
              <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono">
                <span>{schedule.diagnostics.critical_count} critical</span>
                <span>{schedule.diagnostics.milestone_count} milestones</span>
                <span>{schedule.diagnostics.relationships_parsed} logic links</span>
                <span>{schedule.diagnostics.float_coverage_pct}% with float</span>
                <span>{schedule.diagnostics.date_coverage_pct}% with dates</span>
                <span>
                  {schedule.diagnostics.status_breakdown.completed} done ·{" "}
                  {schedule.diagnostics.status_breakdown.in_progress} in progress ·{" "}
                  {schedule.diagnostics.status_breakdown.not_started} not started
                </span>
              </div>
            </details>

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
                  canSubmit={Boolean(schedule) && billing.can_generate}
                  hasBaseline={schedule.has_baseline}
                />
                {!billing.can_generate && (
                  <p className="mt-3 text-sm text-ink-muted">
                    You&rsquo;ve used all {billing.trial_narratives_limit} free narratives.{" "}
                    <Link href="/pricing" className="text-oxide hover:brightness-110 transition-all">
                      Subscribe
                    </Link>{" "}
                    to keep generating.
                  </p>
                )}
                {generateError && <p className="mt-3 text-sm text-oxide">{generateError}</p>}
              </div>
            </div>

            {result && (
              <div className="border-t border-rule pt-8">
                <h2 className="text-xs font-medium uppercase tracking-wider text-ink-muted mb-4">Narrative</h2>
                <NarrativeOutput narrative={result.narrative} />
              </div>
            )}
          </div>
        )}

        <footer className="mt-16 pt-6 border-t border-rule text-xs text-ink-muted">
          <a href="mailto:feedback@schedulenarrative.com" className="hover:text-oxide transition-colors">
            Questions or feedback? feedback@schedulenarrative.com
          </a>
        </footer>
      </div>
    </div>
  );
}
