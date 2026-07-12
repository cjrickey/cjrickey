"use client";

import { useRef, useState } from "react";
import { LogoMark } from "@/components/Logo";

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
    <div className="rounded-xl border border-rule bg-surface shadow-[0_1px_2px_rgba(26,25,23,0.04),0_10px_28px_-14px_rgba(26,25,23,0.12)]">
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
        className={`m-3 rounded-lg border-[1.5px] border-dashed px-6 py-12 text-center cursor-pointer transition-colors ${
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
        <div className="mx-auto mb-4 w-fit opacity-90">
          <LogoMark size={48} />
        </div>
        <p className="text-base font-semibold text-ink">
          {uploading ? "Uploading…" : "Drop a P6 .xer or .xml export here"}
        </p>
        {!uploading && <p className="mt-1 text-xs text-ink-muted">or click to choose a file</p>}
        <span className="mt-4 inline-block rounded-md bg-oxide px-4 py-2 text-sm font-semibold text-white transition-all hover:brightness-110">
          {uploading ? "Working…" : "Choose file"}
        </span>
        <p className="mx-auto mt-5 max-w-md text-xs leading-relaxed text-ink-muted">
          XMLs can be exported with the Project Baseline included &mdash; check that box at export time to unlock
          variance narration. A .xer export never carries baseline data.
        </p>
        {error && <p className="mt-3 text-sm text-oxide">{error}</p>}
      </div>
    </div>
  );
}
