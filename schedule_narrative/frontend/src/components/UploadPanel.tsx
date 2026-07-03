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
    if (!file.name.toLowerCase().endsWith(".xer")) {
      onUpload(file); // let the API's own validation surface the error consistently
      return;
    }
    onUpload(file);
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
      className={`rounded-lg border-2 border-dashed p-10 text-center cursor-pointer transition-colors ${
        dragOver ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-gray-300 dark:border-gray-600"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".xer"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
      <p className="text-sm text-gray-600 dark:text-gray-300">
        {uploading ? "Uploading…" : "Drop a P6 .xer export here, or click to choose a file"}
      </p>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
