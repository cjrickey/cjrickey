"""
Stripe billing: a single $15/month subscription plan, self-serve via
Stripe Checkout, managed (cancel/update card) via the Stripe Customer
Portal, kept in sync with our `subscriptions` table via webhook.

We never store card details ourselves -- Stripe Checkout and the
Customer Portal are both Stripe-hosted pages, so PCI scope stays on
Stripe's side entirely.
"""
import json
import os
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from clerk_auth import require_user
import storage

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

ACTIVE_STATUSES = {"active", "trialing"}

router = APIRouter(prefix="/billing")


def require_active_subscription(user_id: str = Depends(require_user)) -> str:
    """FastAPI dependency: 402 if the signed-in user has no active
    subscription. Returns the user id, so an endpoint can depend on just
    this instead of stacking require_user + a separate check."""
    sub = storage.get_subscription(user_id)
    if sub is None or sub["status"] not in ACTIVE_STATUSES:
        raise HTTPException(402, "An active subscription is required")
    return user_id


@router.get("/status")
def billing_status(user_id: str = Depends(require_user)):
    sub = storage.get_subscription(user_id)
    if sub is None:
        return {"subscribed": False, "status": None}
    return {"subscribed": sub["status"] in ACTIVE_STATUSES, "status": sub["status"]}


@router.post("/create-checkout-session")
def create_checkout_session(user_id: str = Depends(require_user)):
    if not STRIPE_PRICE_ID:
        raise HTTPException(500, "Server is missing STRIPE_PRICE_ID")

    existing = storage.get_subscription(user_id)
    session_kwargs = dict(
        mode="subscription",
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
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
