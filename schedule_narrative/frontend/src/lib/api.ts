import type { ApiErrorBody, NarrativeRequest, NarrativeResponse, UploadResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    return body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function uploadSchedule(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE_URL}/schedules/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
  return res.json();
}

export async function generateNarrative(
  scheduleId: string,
  req: NarrativeRequest,
): Promise<NarrativeResponse> {
  const res = await fetch(`${API_BASE_URL}/schedules/${scheduleId}/narrative`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
  return res.json();
}
