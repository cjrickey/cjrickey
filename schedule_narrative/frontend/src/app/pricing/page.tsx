"use client";

import { Suspense, useState } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import { createCheckoutSession } from "@/lib/api";
import type { BillingPlan } from "@/lib/types";

export default function PricingPage() {
  return (
    <Suspense fallback={null}>
      <PricingContent />
    </Suspense>
  );
}

function PricingContent() {
  const { getToken } = useAuth();
  const searchParams = useSearchParams();
  const cancelled = searchParams.get("checkout") === "cancelled";

  const [plan, setPlan] = useState<BillingPlan>("monthly");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubscribe() {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      const { checkout_url } = await createCheckoutSession(token, plan);
      window.location.href = checkout_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start checkout");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-md px-6 py-16">
        <div className="flex items-center justify-between border-b border-rule pb-6 mb-10">
          <h1 className="text-xl font-semibold tracking-tight">Schedule Narrative</h1>
          <UserButton />
        </div>

        <p className="text-xs uppercase tracking-wide text-ink-muted mb-2">Professional</p>
        <h2 className="text-2xl font-semibold tracking-tight mb-3">Unlimited narratives</h2>
        <p className="text-sm text-ink-muted leading-relaxed mb-8">
          Every free account gets 3 narratives, no card required. Subscribe for unlimited weekly OAC
          and monthly executive narratives, generated from your P6 schedule exports. Cancel any time.
        </p>

        {cancelled && (
          <p className="text-sm text-ochre mb-6">Checkout was cancelled -- no charge was made.</p>
        )}

        <div className="flex gap-1 rounded-sm border border-rule p-0.5 mb-6">
          <button
            type="button"
            onClick={() => setPlan("monthly")}
            className={`flex-1 rounded-sm px-3 py-2 text-sm transition-colors ${
              plan === "monthly" ? "bg-oxide text-white" : "text-ink-muted hover:text-ink"
            }`}
          >
            $22 / month
          </button>
          <button
            type="button"
            onClick={() => setPlan("annual")}
            className={`flex-1 rounded-sm px-3 py-2 text-sm transition-colors ${
              plan === "annual" ? "bg-oxide text-white" : "text-ink-muted hover:text-ink"
            }`}
          >
            $220 / year
          </button>
        </div>

        {plan === "annual" && (
          <p className="text-xs text-ink-muted mb-6 -mt-3">
            Two months free compared to paying monthly.
          </p>
        )}

        <button
          type="button"
          onClick={handleSubscribe}
          disabled={loading}
          className="w-full rounded-sm bg-oxide text-white py-2.5 text-sm font-medium disabled:opacity-40 hover:brightness-110 transition-all"
        >
          {loading ? "Redirecting to checkout…" : "Subscribe"}
        </button>

        {error && <p className="mt-3 text-sm text-oxide">{error}</p>}
      </div>
    </div>
  );
}
