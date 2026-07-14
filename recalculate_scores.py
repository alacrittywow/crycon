#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Recalculate candidate trust scores in Supabase.

Usage:
    python3 recalculate_scores.py
    python3 recalculate_scores.py --id 44
    python3 recalculate_scores.py --limit 50
"""

import argparse
from typing import Any, Dict, List
from urllib.parse import urlparse

from db_supabase import get_supabase_client, clean_text


BAD_CONTACT_FRAGMENTS = [
    "schema.org",
    "cloudflareinsights",
    "googletagmanager",
    "google-analytics",
    "googleapis",
    "gstatic",
    "sentry.io",
    "discourse.org",
    "opensearch.xml",
    ".rss",
    ".xml",
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    "letter_avatar",
    "makerdao-forum-backup.s3",
]


FORUM_DOMAINS = [
    "forum.makerdao.com",
    "forum.skyeco.com",
    "gov.uniswap.org",
    "forum.arbitrum.foundation",
    "governance.aave.com",
    "research.lido.fi",
    "discuss.ens.domains",
]


PLATFORM_DOMAINS = [
    "github.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "t.me",
    "telegram.me",
    "discord.gg",
    "etherscan.io",
    "solscan.io",
    "arbiscan.io",
    "basescan.org",
    "polygonscan.com",
    "optimistic.etherscan.io",
]


def get_domain(value: str) -> str:
    value = clean_text(value)

    if not value:
        return ""

    if not value.startswith("http"):
        return ""

    try:
        parsed = urlparse(value)
        return parsed.netloc.lower()
    except Exception:
        return ""


def is_bad_contact_value(value: str) -> bool:
    value = clean_text(value).lower()

    if not value:
        return True

    return any(fragment in value for fragment in BAD_CONTACT_FRAGMENTS)


def is_forum_url(value: str) -> bool:
    domain = get_domain(value)

    if not domain:
        return False

    return any(forum_domain in domain for forum_domain in FORUM_DOMAINS)


def is_platform_url(value: str) -> bool:
    domain = get_domain(value)

    if not domain:
        return False

    return any(platform_domain in domain for platform_domain in PLATFORM_DOMAINS)


def is_source_or_profile_url(value: str, profiles: List[Dict[str, Any]]) -> bool:
    value = clean_text(value).rstrip("/")

    if not value:
        return False

    for profile in profiles:
        profile_url = clean_text(profile.get("profile_url")).rstrip("/")
        source_url = clean_text(profile.get("source_url")).rstrip("/")

        if value and value in {profile_url, source_url}:
            return True

    return False


def is_real_personal_website(value: str, profiles: List[Dict[str, Any]]) -> bool:
    value = clean_text(value)

    if not value.startswith("http"):
        return False

    if is_bad_contact_value(value):
        return False

    if is_forum_url(value):
        return False

    if is_platform_url(value):
        return False

    if is_source_or_profile_url(value, profiles):
        return False

    domain = get_domain(value)

    if not domain or "." not in domain:
        return False

    return True


def is_useful_contact(contact: Dict[str, Any], profiles: List[Dict[str, Any]]) -> bool:
    contact_type = clean_text(contact.get("contact_type")).lower()
    value = clean_text(contact.get("value"))

    if not value:
        return False

    if is_bad_contact_value(value):
        return False

    if contact_type == "email":
        return "@" in value

    if contact_type == "x":
        return "x.com/" in value or "twitter.com/" in value

    if contact_type == "linkedin":
        return "linkedin.com/" in value

    if contact_type == "github":
        lowered = value.lower()

        if "github.com/discourse" in lowered:
            return False

        return "github.com/" in lowered

    if contact_type == "website":
        return is_real_personal_website(value, profiles)

    return False


def fetch_candidates(client, limit: int = 500) -> List[Dict[str, Any]]:
    response = (
        client
        .table("candidates")
        .select("*")
        .order("id")
        .limit(limit)
        .execute()
    )

    return response.data or []


def fetch_candidate_by_id(client, candidate_id: int) -> Dict[str, Any]:
    response = (
        client
        .table("candidates")
        .select("*")
        .eq("id", candidate_id)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return {}


def fetch_profiles(client, candidate_id: int) -> List[Dict[str, Any]]:
    response = (
        client
        .table("profiles")
        .select("*")
        .eq("candidate_id", candidate_id)
        .execute()
    )

    return response.data or []


def fetch_contacts(client, candidate_id: int) -> List[Dict[str, Any]]:
    response = (
        client
        .table("contacts")
        .select("*")
        .eq("candidate_id", candidate_id)
        .execute()
    )

    return response.data or []


def fetch_wallets(client, candidate_id: int) -> List[Dict[str, Any]]:
    response = (
        client
        .table("wallets")
        .select("*")
        .eq("candidate_id", candidate_id)
        .execute()
    )

    return response.data or []


def status_from_overall(overall: int) -> str:
    if overall >= 80:
        return "strong"

    if overall >= 60:
        return "valid"

    if overall >= 40:
        return "needs_review"

    return "weak"


def calculate_scores(
    candidate: Dict[str, Any],
    profiles: List[Dict[str, Any]],
    contacts: List[Dict[str, Any]],
    wallets: List[Dict[str, Any]],
) -> Dict[str, int | str]:
    relevance_score = int(candidate.get("relevance_score") or 0)

    # identity_score: пока простая версия.
    # Чем больше независимых профилей/контактов — тем увереннее identity.
    identity_score = 50

    if len(profiles) >= 2:
        identity_score += 15

    if len(profiles) >= 3:
        identity_score += 10

    useful_contacts = [
        contact for contact in contacts
        if is_useful_contact(contact, profiles)
    ]

    if useful_contacts:
        identity_score += 10

    if wallets:
        identity_score += 5

    identity_score = min(identity_score, 100)

    # contact_score: учитываем только реально полезные контакты.
    contact_score = 0

    for contact in useful_contacts:
        confidence = int(contact.get("confidence") or 0)
        contact_score = max(contact_score, confidence)

    # wallet_score: кошельки считаем отдельно.
    wallet_score = 0

    for wallet in wallets:
        confidence = int(wallet.get("confidence") or 0)
        wallet_score = max(wallet_score, confidence)

    # source_trust_score: доверие к источникам.
    source_trust_score = 50

    platforms = {
        clean_text(profile.get("platform")).lower()
        for profile in profiles
    }

    if "github" in platforms:
        source_trust_score += 15

    if any(platform.startswith("discourse") for platform in platforms):
        source_trust_score += 15

    source_trust_score = min(source_trust_score, 100)

    contact_wallet_score = max(contact_score, wallet_score)

    overall = int(
        relevance_score * 0.40
        + identity_score * 0.30
        + source_trust_score * 0.20
        + contact_wallet_score * 0.10
    )

    overall = max(0, min(overall, 100))

    return {
        "identity_score": identity_score,
        "wallet_score": wallet_score,
        "contact_score": contact_score,
        "overall_trust_score": overall,
        "status": status_from_overall(overall),
    }


def update_candidate(client, candidate_id: int, scores: Dict[str, int | str]) -> None:
    (
        client
        .table("candidates")
        .update(scores)
        .eq("id", candidate_id)
        .execute()
    )


def recalculate_candidate(client, candidate: Dict[str, Any]) -> Dict[str, Any]:
    candidate_id = int(candidate["id"])

    profiles = fetch_profiles(client, candidate_id)
    contacts = fetch_contacts(client, candidate_id)
    wallets = fetch_wallets(client, candidate_id)

    scores = calculate_scores(
        candidate=candidate,
        profiles=profiles,
        contacts=contacts,
        wallets=wallets,
    )

    old_overall = int(candidate.get("overall_trust_score") or 0)
    old_status = clean_text(candidate.get("status"))

    update_candidate(client, candidate_id, scores)

    return {
        "candidate_id": candidate_id,
        "username": candidate.get("main_username"),
        "old_overall": old_overall,
        "new_overall": scores["overall_trust_score"],
        "old_status": old_status,
        "new_status": scores["status"],
        "contact_score": scores["contact_score"],
        "wallet_score": scores["wallet_score"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recalculate Mirae trust scores."
    )

    parser.add_argument(
        "--id",
        type=int,
        help="Recalculate one candidate by ID",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max candidates to recalculate",
    )

    args = parser.parse_args()

    client = get_supabase_client()

    print("=" * 90)
    print("Mirae Score Recalculation")
    print("=" * 90)

    if args.id:
        candidate = fetch_candidate_by_id(client, args.id)

        if not candidate:
            print(f"Candidate not found: {args.id}")
            return

        candidates = [candidate]

    else:
        candidates = fetch_candidates(client, args.limit)

    print(f"Candidates: {len(candidates)}")
    print("=" * 90)

    for candidate in candidates:
        result = recalculate_candidate(client, candidate)

        print(
            f"candidate_id={result['candidate_id']} "
            f"username={result['username']} "
            f"overall {result['old_overall']} → {result['new_overall']} "
            f"status {result['old_status']} → {result['new_status']} "
            f"contact_score={result['contact_score']} "
            f"wallet_score={result['wallet_score']}"
        )

    print("=" * 90)
    print("Done")
    print("=" * 90)


if __name__ == "__main__":
    main()