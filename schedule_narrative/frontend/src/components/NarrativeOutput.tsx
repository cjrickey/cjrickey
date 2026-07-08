"use client";

import { useState } from "react";

type NarrativeOutputProps = {
  narrative: string;
  filteredPayload: unknown;
};

export function NarrativeOutput({ narrative, filteredPayload }: NarrativeOutputProps) {
  const [showData, setShowData] = useState(false);

  return (
    <div className="space-y-4">
      <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink max-w-[65ch]">{narrative}</p>

      <button
        type="button"
        onClick={() => setShowData((v) => !v)}
        className="text-xs text-ink-muted hover:text-oxide transition-colors"
      >
        {showData ? "Hide underlying data" : "Show underlying data"}
      </button>

      {showData && (
        <pre className="rounded-sm border border-rule bg-surface p-3 text-xs font-mono overflow-x-auto max-h-96 overflow-y-auto text-ink-muted">
          {JSON.stringify(filteredPayload, null, 2)}
        </pre>
      )}
    </div>
  );
}
