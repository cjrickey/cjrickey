"use client";

import { useRef, useState } from "react";

type UploadPanelProps = {
  onUpload: (file: File) => void;
  uploading: boolean;
  error: string | null;
};

export function UploadPanel({ onUpload, uploading, error }: UploadPanelProps) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File | undefined) {
    if (!file) return;
    onUpload(file); // backend sniffs XER vs XML by content, not filename -- let it validate
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFile(e.dataTransfer.files[0]);
      }}
      onClick={() => inputRef.current?.click()}
      className={`border border-dashed rounded-sm p-14 text-center cursor-pointer transition-colors ${
        dragOver ? "border-oxide bg-oxide-surface" : "border-rule hover:border-ink-muted"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".xer,.xml"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
      <p className="text-sm text-ink">
        {uploading ? "Uploading…" : "Drop a P6 .xer or .xml export, or click to choose a file"}
      </p>
      <p className="mt-2 text-xs text-ink-muted">
        Only a .xml export with the Project Baseline included unlocks variance vs. baseline. A .xer export never
        carries baseline data.
      </p>
      {error && <p className="mt-3 text-sm text-oxide">{error}</p>}
    </div>
  );
}
