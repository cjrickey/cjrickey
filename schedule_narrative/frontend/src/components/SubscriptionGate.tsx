"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { getBillingStatus } from "@/lib/api";

export function SubscriptionGate({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const router = useRouter();
  const [subscribed, setSubscribed] = useState(false);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      router.replace("/sign-in");
      return;
    }
    let cancelled = false;
    (async () => {
      const token = await getToken();
      if (!token || cancelled) return;
      try {
        const res = await getBillingStatus(token);
        if (cancelled) return;
        if (res.subscribed) {
          setSubscribed(true);
        } else {
          router.replace("/pricing");
        }
      } catch {
        if (!cancelled) router.replace("/pricing");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken, router]);

  if (!subscribed) {
    return <p className="mx-auto max-w-4xl px-6 py-12 text-sm text-ink-muted">Checking your subscription…</p>;
  }
  return <>{children}</>;
}
