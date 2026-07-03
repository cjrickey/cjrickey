"use client";

import { useState } from "react";

type NarrativeOutputProps = {
  narrative: string;
  filteredPayload: unknown;
};

export function NarrativeOutput({ narrative, filteredPayload }: NarrativeOutputProps) {
  const [showData, setShowData] = useState(false);

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-900 dark:text-gray-100">{narrative}</p>
      </div>

      <button
        type="button"
        onClick={() => setShowData((v) => !v)}
        className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
      >
        {showData ? "Hide underlying data" : "Show underlying data"}
      </button>

      {showData && (
        <pre className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3 text-xs overflow-x-auto max-h-96 overflow-y-auto">
          {JSON.stringify(filteredPayload, null, 2)}
        </pre>
      )}
    </div>
  );
}
