"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { getBillingStatus } from "@/lib/api";
import { BillingContext } from "@/lib/BillingContext";
import type { BillingStatus } from "@/lib/types";

export function SubscriptionGate({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<BillingStatus | null>(null);

  const refresh = useCallback(async () => {
    const token = await getToken();
    if (!token) return;
    setStatus(await getBillingStatus(token));
  }, [getToken]);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      router.replace("/sign-in");
      return;
    }
    refresh();
  }, [isLoaded, isSignedIn, refresh, router]);

  if (!status) {
    return <p className="mx-auto max-w-4xl px-6 py-12 text-sm text-ink-muted">Loading…</p>;
  }

  return <BillingContext.Provider value={{ status, refresh }}>{children}</BillingContext.Provider>;
}
