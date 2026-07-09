"""
Stripe billing: a free trial (TRIAL_LIMIT narratives, no card required),
then Professional -- $22/month or $220/year (two months free) for
unlimited narratives. Self-serve via Stripe Checkout; managed
(cancel/update card) via the Stripe Customer Portal; kept in sync with
our `subscriptions` table via webhook.

We never store card details ourselves -- Stripe Checkout and the
Customer Portal are both Stripe-hosted pages, so PCI scope stays on
Stripe's side entirely.
"""
import json
import os
from typing import Literal, Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from clerk_auth import require_user
import storage

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID_MONTHLY = os.environ.get("STRIPE_PRICE_ID_MONTHLY")
STRIPE_PRICE_ID_ANNUAL = os.environ.get("STRIPE_PRICE_ID_ANNUAL")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

TRIAL_LIMIT = int(os.environ.get("TRIAL_NARRATIVE_LIMIT", "3"))

# Clerk user ids (comma-separated) that bypass the trial/subscription gate
# entirely -- for the app's own operator(s), not a general-purpose feature.
ADMIN_USER_IDS = {uid.strip() for uid in os.environ.get("ADMIN_USER_IDS", "").split(",") if uid.strip()}

ACTIVE_STATUSES = {"active", "trialing"}

router = APIRouter(prefix="/billing")


def require_narrative_access(user_id: str = Depends(require_user)) -> str:
    """FastAPI dependency: allows a signed-in user through if they're an
    admin, have an active subscription, or haven't used up their free
    trial (TRIAL_LIMIT narratives, no card required) yet. 402 otherwise."""
    if user_id in ADMIN_USER_IDS:
        return user_id
    sub = storage.get_subscription(user_id)
    if sub is not None and sub["status"] in ACTIVE_STATUSES:
        return user_id
    if storage.get_total_narrative_count(user_id) < TRIAL_LIMIT:
        return user_id
    raise HTTPException(402, "Free trial used up -- subscribe to keep generating narratives")


@router.get("/status")
def billing_status(user_id: str = Depends(require_user)):
    if user_id in ADMIN_USER_IDS:
        return {
            "subscribed": True,
            "status": "admin",
            "trial_narratives_used": 0,
            "trial_narratives_limit": TRIAL_LIMIT,
            "trial_remaining": TRIAL_LIMIT,
            "can_generate": True,
        }
    sub = storage.get_subscription(user_id)
    subscribed = sub is not None and sub["status"] in ACTIVE_STATUSES
    used = storage.get_total_narrative_count(user_id)
    return {
        "subscribed": subscribed,
        "status": sub["status"] if sub else None,
        "trial_narratives_used": used,
        "trial_narratives_limit": TRIAL_LIMIT,
        "trial_remaining": max(TRIAL_LIMIT - used, 0),
        "can_generate": subscribed or used < TRIAL_LIMIT,
    }


class CheckoutRequest(BaseModel):
    plan: Literal["monthly", "annual"] = "monthly"


@router.post("/create-checkout-session")
def create_checkout_session(req: CheckoutRequest, user_id: str = Depends(require_user)):
    price_id = STRIPE_PRICE_ID_ANNUAL if req.plan == "annual" else STRIPE_PRICE_ID_MONTHLY
    if not price_id:
        raise HTTPException(500, f"Server is missing the Stripe price id for the {req.plan} plan")

    existing = storage.get_subscription(user_id)
    session_kwargs = dict(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        client_reference_id=user_id,
        success_url=f"{FRONTEND_ORIGIN}/?checkout=success",
        cancel_url=f"{FRONTEND_ORIGIN}/pricing?checkout=cancelled",
    )
    # Reuse the existing Stripe customer if this user has one (e.g. a
    # lapsed/canceled subscriber resubscribing) so billing history stays
    # attached to one customer record instead of forking a new one.
    if existing and existing["stripe_customer_id"]:
        session_kwargs["customer"] = existing["stripe_customer_id"]

    session = stripe.checkout.Session.create(**session_kwargs)
    return {"checkout_url": session.url}


@router.post("/create-portal-session")
def create_portal_session(user_id: str = Depends(require_user)):
    sub = storage.get_subscription(user_id)
    if sub is None or not sub["stripe_customer_id"]:
        raise HTTPException(404, "No billing account found -- subscribe first")

    portal = stripe.billing_portal.Session.create(
        customer=sub["stripe_customer_id"],
        return_url=f"{FRONTEND_ORIGIN}/",
    )
    return {"portal_url": portal.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(default=None)):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Server is missing STRIPE_WEBHOOK_SECRET")

    payload = (await request.body()).decode("utf-8")
    try:
        # Verify the signature without letting the SDK wrap the payload in
        # its own Event/StripeObject types -- those don't behave like plain
        # dicts across SDK versions (e.g. no .get()), so we parse the raw
        # JSON ourselves once the signature is confirmed authentic. Must be
        # a str, not bytes -- verify_header builds "timestamp.payload" via
        # %s formatting, which stringifies bytes as "b'...'" and breaks
        # every signature check.
        stripe.WebhookSignature.verify_header(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
        event = json.loads(payload)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(400, f"Invalid webhook payload/signature: {exc}") from exc

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        if user_id and customer_id:
            status = "active"
            if subscription_id:
                status = stripe.Subscription.retrieve(subscription_id)["status"]
            storage.upsert_subscription(
                user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                status=status,
            )

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        user_id = storage.get_user_id_for_customer(obj.get("customer"))
        if user_id:
            period_end = obj.get("current_period_end")
            storage.upsert_subscription(
                user_id,
                stripe_subscription_id=obj.get("id"),
                status=obj.get("status"),
                current_period_end=str(period_end) if period_end else None,
            )

    elif event_type == "customer.subscription.deleted":
        user_id = storage.get_user_id_for_customer(obj.get("customer"))
        if user_id:
            storage.upsert_subscription(user_id, status="canceled")

    elif event_type == "invoice.payment_failed":
        user_id = storage.get_user_id_for_customer(obj.get("customer"))
        if user_id:
            storage.upsert_subscription(user_id, status="past_due")

    return {"received": True}
