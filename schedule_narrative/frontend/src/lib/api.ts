import type {
  ApiErrorBody,
  BillingStatus,
  NarrativeRequest,
  NarrativeResponse,
  UploadResponse,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    return body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function uploadSchedule(file: File, token: string): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE_URL}/schedules/upload`, {
    method: "POST",
    headers: authHeaders(token),
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
  token: string,
): Promise<NarrativeResponse> {
  const res = await fetch(`${API_BASE_URL}/schedules/${scheduleId}/narrative`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
  return res.json();
}

export async function getBillingStatus(token: string): Promise<BillingStatus> {
  const res = await fetch(`${API_BASE_URL}/billing/status`, {
    headers: authHeaders(token),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
  return res.json();
}

export async function createCheckoutSession(token: string): Promise<{ checkout_url: string }> {
  const res = await fetch(`${API_BASE_URL}/billing/create-checkout-session`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
  return res.json();
}

export async function createPortalSession(token: string): Promise<{ portal_url: string }> {
  const res = await fetch(`${API_BASE_URL}/billing/create-portal-session`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res));
  }
  return res.json();
}
