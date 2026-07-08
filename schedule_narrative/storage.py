"""
Persistence layer, backed by SQLAlchemy Core so the same code runs against
local SQLite (zero-setup dev default) or production Postgres (set
DATABASE_URL, e.g. Render's managed Postgres connection string).

Schedules and usage counts are scoped per user (owner_user_id -- the Clerk
user id) now that this is a multi-tenant product: one user must never be
able to load another user's uploaded schedule by guessing a schedule_id.

Activity round-trips through JSON via to_dict() / Activity(**dict) -- the
dict's keys already match the dataclass fields one-to-one, so no separate
serialization schema is needed.
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
)

from activity_extractor import Activity

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///schedules.db")

# Render (and most Postgres hosts) hand out a "postgres://" URL, but
# SQLAlchemy's psycopg2 dialect requires the "postgresql://" scheme.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()

schedules = Table(
    "schedules",
    metadata,
    Column("schedule_id", String, primary_key=True),
    Column("owner_user_id", String, nullable=False, index=True),
    Column("data_date", String, nullable=False),
    Column("activities", Text, nullable=False),
    Column("wbs_tree", Text, nullable=False),
    Column("created_at", String, nullable=False),
)

narrative_usage = Table(
    "narrative_usage",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("day", String, primary_key=True),
    Column("count", Integer, nullable=False),
)

subscriptions = Table(
    "subscriptions",
    metadata,
    Column("clerk_user_id", String, primary_key=True),
    Column("stripe_customer_id", String, unique=True, index=True),
    Column("stripe_subscription_id", String),
    Column("status", String, nullable=False),  # active | trialing | past_due | canceled | incomplete
    Column("current_period_end", String),
    Column("updated_at", String, nullable=False),
)

metadata.create_all(engine)


def save_schedule(
    schedule_id: str,
    owner_user_id: str,
    data_date: datetime,
    activities: list[Activity],
    wbs_tree: list[dict],
) -> None:
    with engine.begin() as conn:
        conn.execute(
            schedules.delete().where(schedules.c.schedule_id == schedule_id)
        )
        conn.execute(
            schedules.insert().values(
                schedule_id=schedule_id,
                owner_user_id=owner_user_id,
                data_date=data_date.isoformat(),
                activities=json.dumps([a.to_dict() for a in activities]),
                wbs_tree=json.dumps(wbs_tree),
                created_at=datetime.utcnow().isoformat(),
            )
        )


def load_schedule(schedule_id: str, owner_user_id: str) -> Optional[dict]:
    """Returns None if the schedule doesn't exist OR belongs to a different
    user -- callers can't distinguish "not found" from "not yours", which is
    the point: don't leak whether a given schedule_id exists to a user who
    doesn't own it."""
    with engine.connect() as conn:
        row = conn.execute(
            select(schedules.c.data_date, schedules.c.activities, schedules.c.wbs_tree).where(
                schedules.c.schedule_id == schedule_id,
                schedules.c.owner_user_id == owner_user_id,
            )
        ).fetchone()

    if row is None:
        return None

    data_date_str, activities_json, wbs_tree_json = row
    return {
        "data_date": datetime.fromisoformat(data_date_str),
        "activities": [Activity(**d) for d in json.loads(activities_json)],
        "wbs_tree": json.loads(wbs_tree_json),
    }


def get_usage_count(user_id: str, day: str) -> int:
    with engine.connect() as conn:
        row = conn.execute(
            select(narrative_usage.c.count).where(
                narrative_usage.c.user_id == user_id,
                narrative_usage.c.day == day,
            )
        ).fetchone()
    return row[0] if row else 0


def increment_usage(user_id: str, day: str) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            select(narrative_usage.c.count).where(
                narrative_usage.c.user_id == user_id,
                narrative_usage.c.day == day,
            )
        ).fetchone()
        if row is None:
            conn.execute(narrative_usage.insert().values(user_id=user_id, day=day, count=1))
            return 1
        conn.execute(
            narrative_usage.update()
            .where(narrative_usage.c.user_id == user_id, narrative_usage.c.day == day)
            .values(count=row[0] + 1)
        )
        return row[0] + 1


def get_subscription(clerk_user_id: str) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(
            select(
                subscriptions.c.stripe_customer_id,
                subscriptions.c.stripe_subscription_id,
                subscriptions.c.status,
                subscriptions.c.current_period_end,
            ).where(subscriptions.c.clerk_user_id == clerk_user_id)
        ).fetchone()
    if row is None:
        return None
    return {
        "stripe_customer_id": row[0],
        "stripe_subscription_id": row[1],
        "status": row[2],
        "current_period_end": row[3],
    }


def get_user_id_for_customer(stripe_customer_id: str) -> Optional[str]:
    with engine.connect() as conn:
        row = conn.execute(
            select(subscriptions.c.clerk_user_id).where(
                subscriptions.c.stripe_customer_id == stripe_customer_id
            )
        ).fetchone()
    return row[0] if row else None


def upsert_subscription(
    clerk_user_id: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    status: Optional[str] = None,
    current_period_end: Optional[str] = None,
) -> None:
    """Partial update: only overwrites fields that are passed in, so a
    webhook that only knows the subscription status doesn't have to also
    know (and risk blanking) the customer id."""
    with engine.begin() as conn:
        existing = conn.execute(
            select(subscriptions.c.clerk_user_id).where(subscriptions.c.clerk_user_id == clerk_user_id)
        ).fetchone()

        updated_at = datetime.utcnow().isoformat()
        if existing is None:
            conn.execute(
                subscriptions.insert().values(
                    clerk_user_id=clerk_user_id,
                    stripe_customer_id=stripe_customer_id,
                    stripe_subscription_id=stripe_subscription_id,
                    status=status or "incomplete",
                    current_period_end=current_period_end,
                    updated_at=updated_at,
                )
            )
            return

        values = {"updated_at": updated_at}
        if stripe_customer_id is not None:
            values["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id is not None:
            values["stripe_subscription_id"] = stripe_subscription_id
        if status is not None:
            values["status"] = status
        if current_period_end is not None:
            values["current_period_end"] = current_period_end

        conn.execute(
            subscriptions.update().where(subscriptions.c.clerk_user_id == clerk_user_id).values(**values)
        )
