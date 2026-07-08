"use client";

import { createContext, useContext } from "react";
import type { BillingStatus } from "./types";

export type BillingContextValue = {
  status: BillingStatus;
  refresh: () => Promise<void>;
};

export const BillingContext = createContext<BillingContextValue | null>(null);

export function useBilling(): BillingContextValue {
  const ctx = useContext(BillingContext);
  if (!ctx) throw new Error("useBilling must be used inside SubscriptionGate");
  return ctx;
}
