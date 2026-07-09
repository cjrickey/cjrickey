import { clerkMiddleware } from "@clerk/nextjs/server";

// Next.js 16 renamed this file's convention to `proxy.ts`, but Vercel's
// production request routing didn't yet invoke it correctly (build
// succeeded, every route 404'd in production) -- reverted to the older
// `middleware.ts` convention, which Next.js explicitly kept working
// (deprecated, not removed) for exactly this kind of platform gap.
//
// This just makes Clerk's session available on every request; it does
// NOT gate access -- Clerk deprecated route-matcher-based protection here
// in favor of resource-based checks (auth verified where the protected
// data actually lives). That's already how this app works: the frontend
// (SubscriptionGate) redirects signed-out/unsubscribed users for UX, and
// the backend (clerk_auth.require_user + billing.require_active_subscription)
// is the real enforcement boundary, since the backend never trusts
// anything the frontend claims about auth state.
export default clerkMiddleware();

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
