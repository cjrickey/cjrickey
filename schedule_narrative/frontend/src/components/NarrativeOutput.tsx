"use client";

type NarrativeOutputProps = {
  narrative: string;
};

export function NarrativeOutput({ narrative }: NarrativeOutputProps) {
  return <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink max-w-[65ch]">{narrative}</p>;
}
