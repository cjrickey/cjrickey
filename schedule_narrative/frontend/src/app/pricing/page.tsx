"use client";

import { Suspense, useState } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import { createCheckoutSession } from "@/lib/api";

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

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubscribe() {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not signed in");
      const { checkout_url } = await createCheckoutSession(token);
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

        <p className="text-xs uppercase tracking-wide text-ink-muted mb-2">Subscription required</p>
        <h2 className="text-2xl font-semibold tracking-tight mb-3">$15 / month</h2>
        <p className="text-sm text-ink-muted leading-relaxed mb-8">
          Unlimited weekly OAC and monthly executive narratives, generated from your P6 schedule
          exports. Cancel any time.
        </p>

        {cancelled && (
          <p className="text-sm text-ochre mb-6">Checkout was cancelled -- no charge was made.</p>
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
