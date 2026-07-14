#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Search candidates in Supabase.

Usage:
    python3 search_candidate.py alice
    python3 search_candidate.py --id 12
    python3 search_candidate.py --top 20
"""

import argparse
from typing import Any, Dict, List, Set

from db_supabase import get_supabase_client, clean_text


def short(value: Any, max_len: int = 300) -> str:
    text = clean_text(value)

    if len(text) <= max_len:
        return text

    return text[:max_len].rstrip() + "..."


def fetch_candidate(client, candidate_id: int) -> Dict[str, Any]:
    response = (
        client
        .table("candidates")
        .select("*")
        .eq("id", candidate_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        return {}

    return response.data[0]


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


def fetch_evidence(client, candidate_id: int) -> List[Dict[str, Any]]:
    response = (
        client
        .table("evidence")
        .select("*")
        .eq("candidate_id", candidate_id)
        .order("confidence", desc=True)
        .limit(10)
        .execute()
    )

    return response.data or []


def add_candidate_ids_from_response(
    candidate_ids: Set[int],
    response_data: List[Dict[str, Any]],
    id_field: str = "id",
) -> None:
    for item in response_data or []:
        value = item.get(id_field)

        if value is None:
            continue

        try:
            candidate_ids.add(int(value))
        except ValueError:
            continue


def search_by_text(client, query: str, limit: int = 20) -> List[int]:
    """
    Ищем кандидатов по:
    - candidates.main_username
    - candidates.display_name
    - profiles.username
    - profiles.display_name
    - contacts.value
    - wallets.wallet_address
    - wallets.name_service
    """
    query = clean_text(query)

    if not query:
        return []

    candidate_ids: Set[int] = set()

    # 1. candidates.main_username
    response = (
        client
        .table("candidates")
        .select("id")
        .ilike("main_username", f"%{query}%")
        .limit(limit)
        .execute()
    )
    add_candidate_ids_from_response(candidate_ids, response.data, "id")

    # 2. candidates.display_name
    response = (
        client
        .table("candidates")
        .select("id")
        .ilike("display_name", f"%{query}%")
        .limit(limit)
        .execute()
    )
    add_candidate_ids_from_response(candidate_ids, response.data, "id")

    # 3. profiles.username
    response = (
        client
        .table("profiles")
        .select("candidate_id")
        .ilike("username", f"%{query}%")
        .limit(limit)
        .execute()
    )
    add_candidate_ids_from_response(candidate_ids, response.data, "candidate_id")

    # 4. profiles.display_name
    response = (
        client
        .table("profiles")
        .select("candidate_id")
        .ilike("display_name", f"%{query}%")
        .limit(limit)
        .execute()
    )
    add_candidate_ids_from_response(candidate_ids, response.data, "candidate_id")

    # 5. contacts.value
    response = (
        client
        .table("contacts")
        .select("candidate_id")
        .ilike("value", f"%{query}%")
        .limit(limit)
        .execute()
    )
    add_candidate_ids_from_response(candidate_ids, response.data, "candidate_id")

    # 6. wallets.wallet_address
    response = (
        client
        .table("wallets")
        .select("candidate_id")
        .ilike("wallet_address", f"%{query}%")
        .limit(limit)
        .execute()
    )
    add_candidate_ids_from_response(candidate_ids, response.data, "candidate_id")

    # 7. wallets.name_service
    response = (
        client
        .table("wallets")
        .select("candidate_id")
        .ilike("name_service", f"%{query}%")
        .limit(limit)
        .execute()
    )
    add_candidate_ids_from_response(candidate_ids, response.data, "candidate_id")

    return list(candidate_ids)[:limit]


def get_top_candidates(client, limit: int = 20) -> List[int]:
    response = (
        client
        .table("candidates")
        .select("id")
        .order("overall_trust_score", desc=True)
        .limit(limit)
        .execute()
    )

    candidate_ids = []

    for item in response.data or []:
        candidate_ids.append(item["id"])

    return candidate_ids

def print_candidate_card(client, candidate_id: int, full: bool = False) -> None:
    candidate = fetch_candidate(client, candidate_id)

    if not candidate:
        print(f"Candidate not found: {candidate_id}")
        return

    profiles = fetch_profiles(client, candidate_id)
    contacts = fetch_contacts(client, candidate_id)
    wallets = fetch_wallets(client, candidate_id)
    evidence = fetch_evidence(client, candidate_id)

    print("=" * 90)
    print(f"Candidate ID: {candidate.get('id')}")
    print(f"Username:     {candidate.get('main_username')}")
    print(f"Display name: {candidate.get('display_name') or ''}")
    print(f"Status:       {candidate.get('status')}")
    print()
    print(f"Overall trust: {candidate.get('overall_trust_score')}/100")
    print(f"Relevance:     {candidate.get('relevance_score')}/100")
    print(f"Identity:      {candidate.get('identity_score')}/100")
    print(f"Wallet score:  {candidate.get('wallet_score')}/100")
    print(f"Contact score: {candidate.get('contact_score')}/100")
    print()

    bio = clean_text(candidate.get("bio"))

    if bio:
        print("Bio:")
        print(short(bio, 500))
        print()

    print("Profiles:")
    if profiles:
        for profile in profiles:
            platform = profile.get("platform")
            username = profile.get("username")
            profile_url = profile.get("profile_url") or ""
            source_url = profile.get("source_url") or ""
            confidence = profile.get("confidence")

            print(f"- {platform}: {username}")
            print(f"  profile:    {profile_url}")
            print(f"  source:     {source_url}")
            print(f"  confidence: {confidence}")
    else:
        print("- none")

    print()

    if not full:
        print("=" * 90)
        print()
        return

    print("Contacts:")

    useful_contacts = []
    bad_contact_fragments = [
        "schema.org",
        "cloudflareinsights",
        "googletagmanager",
        "discourse.org",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".css",
        ".js",
        ".xml",
        ".rss",
        "letter_avatar",
        "makerdao-forum-backup.s3",
    ]

    for contact in contacts:
        value = str(contact.get("value") or "").lower()

        if any(fragment in value for fragment in bad_contact_fragments):
            continue

        useful_contacts.append(contact)

    useful_contacts = sorted(
        useful_contacts,
        key=lambda item: int(item.get("confidence") or 0),
        reverse=True,
    )

    if useful_contacts:
        for contact in useful_contacts[:10]:
            print(
                f"- {contact.get('contact_type')}: "
                f"{contact.get('value')} "
                f"| confidence={contact.get('confidence')} "
                f"| status={contact.get('status')}"
            )
            if contact.get("evidence_url"):
                print(f"  evidence: {contact.get('evidence_url')}")

        if len(useful_contacts) > 10:
            print(f"- ... hidden {len(useful_contacts) - 10} more contacts")
    else:
        print("- none")

    print("Wallets:")
    if wallets:
        for wallet in wallets:
            wallet_value = wallet.get("wallet_address") or wallet.get("name_service")
            print(
                f"- {wallet.get('wallet_type')}: "
                f"{wallet_value} "
                f"| chain={wallet.get('chain') or ''} "
                f"| confidence={wallet.get('confidence')} "
                f"| status={wallet.get('status')}"
            )
            if wallet.get("evidence_url"):
                print(f"  evidence: {wallet.get('evidence_url')}")
            if wallet.get("evidence_text"):
                print(f"  text: {short(wallet.get('evidence_text'), 200)}")
    else:
        print("- none")

    print()

    print("Evidence:")

    useful_evidence = []

    for item in evidence:
        entity_type = str(item.get("entity_type") or "").lower()
        entity_value = str(item.get("entity_value") or "").lower()

        if entity_type == "website":
            if any(fragment in entity_value for fragment in bad_contact_fragments):
                continue

        useful_evidence.append(item)

    useful_evidence = sorted(
        useful_evidence,
        key=lambda item: int(item.get("confidence") or 0),
        reverse=True,
    )

    if useful_evidence:
        for item in useful_evidence[:7]:
            print(
                f"- {item.get('entity_type')}: "
                f"{item.get('entity_value') or ''} "
                f"| confidence={item.get('confidence')}"
            )
            if item.get("source_url"):
                print(f"  source: {item.get('source_url')}")
            if item.get("evidence_text"):
                print(f"  text: {short(item.get('evidence_text'), 250)}")

        if len(useful_evidence) > 7:
            print(f"- ... hidden {len(useful_evidence) - 7} more evidence rows")
    else:
        print("- none")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search Mirae Web3 candidates in Supabase."
    )

    parser.add_argument(
        "query",
        nargs="?",
        help="Nickname, display name, wallet, ENS, .sol, contact value",
    )

    parser.add_argument(
        "--id",
        type=int,
        help="Open exact candidate ID",
    )

    parser.add_argument(
        "--top",
        type=int,
        help="Show top candidates by trust score",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Search result limit",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Show contacts, wallets and evidence",
    )

    args = parser.parse_args()

    client = get_supabase_client()

    if args.id:
        print_candidate_card(client, args.id)
        return

    if args.top:
        candidate_ids = get_top_candidates(client, limit=args.top)

        print("=" * 90)
        print(f"Top candidates: {len(candidate_ids)}")
        print("=" * 90)

        for candidate_id in candidate_ids:
            print_candidate_card(client, candidate_id, full=args.full)

        return

    if not args.query:
        print("Usage:")
        print("  python3 search_candidate.py <nickname>")
        print("  python3 search_candidate.py --id 12")
        print("  python3 search_candidate.py --top 20")
        return

    candidate_ids = search_by_text(
        client=client,
        query=args.query,
        limit=args.limit,
    )

    print("=" * 90)
    print(f"Search query: {args.query}")
    print(f"Matches: {len(candidate_ids)}")
    print("=" * 90)

    if not candidate_ids:
        print("No matches found.")
        return

    for candidate_id in candidate_ids:
        print_candidate_card(client, candidate_id, full=args.full)


if __name__ == "__main__":
    main()