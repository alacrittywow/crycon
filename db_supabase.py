#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from typing import Any, Dict, List, Optional

from supabase import create_client, Client


def load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()


def get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()

    if not url:
        raise RuntimeError("SUPABASE_URL is missing in .env")

    if not key:
        raise RuntimeError("SUPABASE_KEY is missing in .env")

    return create_client(url, key)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def calculate_relevance_score(record: Dict[str, Any]) -> int:
    text = " ".join([
        clean_text(record.get("username")),
        clean_text(record.get("display_name")),
        clean_text(record.get("bio")),
        clean_text(record.get("matched_keyword")),
        clean_text(record.get("source")),
    ]).lower()

    score = 0

    strong_keywords = [
        "validator",
        "governance",
        "delegate",
        "dao",
        "defi",
        "protocol",
        "staking",
        "solana",
        "ethereum",
        "web3",
        "grant",
        "proposal",
    ]

    for keyword in strong_keywords:
        if keyword in text:
            score += 10

    source = clean_text(record.get("source")).lower()

    if source == "github":
        score += 20

    if source.startswith("discourse"):
        score += 25

    if clean_text(record.get("bio")):
        score += 10

    if clean_text(record.get("profile_url")):
        score += 10

    if clean_text(record.get("source_url")):
        score += 10

    spam_words = [
        "scam",
        "malware",
        "drained",
        "recovery",
        "guaranteed profit",
        "airdrop scam",
    ]

    for word in spam_words:
        if word in text:
            score -= 40

    return max(0, min(score, 100))


def status_from_score(score: int) -> str:
    if score >= 80:
        return "strong"

    if score >= 60:
        return "valid"

    if score >= 40:
        return "needs_review"

    return "weak"


def find_existing_profile(
    client: Client,
    platform: str,
    username: str,
) -> Optional[Dict[str, Any]]:
    response = (
        client
        .table("profiles")
        .select("*")
        .eq("platform", platform)
        .eq("username", username)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def insert_candidate_with_profile_and_evidence(
    client: Client,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    source = clean_text(record.get("source"))
    username = clean_text(record.get("username"))

    if not source or not username:
        return {
            "status": "skipped",
            "reason": "missing source or username",
        }

    existing_profile = find_existing_profile(
        client=client,
        platform=source,
        username=username,
    )

    if existing_profile:
        return {
            "status": "exists",
            "candidate_id": existing_profile.get("candidate_id"),
            "profile_id": existing_profile.get("id"),
        }

    relevance_score = calculate_relevance_score(record)

    candidate_payload = {
        "main_username": username,
        "display_name": clean_text(record.get("display_name")),
        "bio": clean_text(record.get("bio")),
        "relevance_score": relevance_score,
        "identity_score": 50,
        "wallet_score": 0,
        "contact_score": 0,
        "overall_trust_score": relevance_score,
        "status": status_from_score(relevance_score),
    }

    candidate_response = (
        client
        .table("candidates")
        .insert(candidate_payload)
        .execute()
    )

    if not candidate_response.data:
        raise RuntimeError("Failed to insert candidate")

    candidate = candidate_response.data[0]
    candidate_id = candidate["id"]

    profile_payload = {
        "candidate_id": candidate_id,
        "platform": source,
        "username": username,
        "display_name": clean_text(record.get("display_name")),
        "bio": clean_text(record.get("bio")),
        "profile_url": clean_text(record.get("profile_url")),
        "source_url": clean_text(record.get("source_url")),
        "matched_keyword": clean_text(record.get("matched_keyword")),
        "confidence": 70,
        "evidence_type": "parser_discovery",
    }

    profile_response = (
        client
        .table("profiles")
        .insert(profile_payload)
        .execute()
    )

    if not profile_response.data:
        raise RuntimeError("Failed to insert profile")

    source_url = (
        clean_text(record.get("source_url"))
        or clean_text(record.get("profile_url"))
    )

    evidence_payload = {
        "candidate_id": candidate_id,
        "entity_type": "candidate_discovery",
        "entity_value": username,
        "source_platform": source,
        "source_url": source_url,
        "evidence_text": (
            "Discovered by parser. "
            f"Matched keyword: {clean_text(record.get('matched_keyword'))}"
        ),
        "confidence": 70,
    }

    evidence_response = (
        client
        .table("evidence")
        .insert(evidence_payload)
        .execute()
    )

    if not evidence_response.data:
        raise RuntimeError("Failed to insert evidence")

    return {
        "status": "created",
        "candidate_id": candidate_id,
        "profile_id": profile_response.data[0]["id"],
        "evidence_id": evidence_response.data[0]["id"],
        "relevance_score": relevance_score,
    }


def create_parser_job(
    client: Client,
    job_type: str,
    query: str,
    status: str = "running",
) -> Optional[int]:
    response = (
        client
        .table("parser_jobs")
        .insert({
            "job_type": job_type,
            "query": query,
            "status": status,
            "result_count": 0,
        })
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]["id"]


def finish_parser_job(
    client: Client,
    job_id: int,
    result_count: int,
    status: str = "done",
) -> None:
    (
        client
        .table("parser_jobs")
        .update({
            "status": status,
            "result_count": result_count,
        })
        .eq("id", job_id)
        .execute()
    )


# ========== НОВЫЕ ФУНКЦИИ ДЛЯ УЛУЧШЕННОГО ПОИСКА ==========

def refresh_search_view(client: Client) -> None:
    """Обновить материализованное представление для поиска."""
    client.sql("REFRESH MATERIALIZED VIEW mv_candidate_search").execute()


def search_candidate_ids(
    client: Client,
    query: str,
    limit: int = 10,
) -> List[int]:
    """
    Умный поиск кандидатов.
    Приоритет:
    1) точное совпадение адреса кошелька или name_service;
    2) точное совпадение username в профилях;
    3) точное совпадение main_username;
    4) синоним (known_aliases);
    5) нечёткий поиск через pg_trgm;
    6) запасной ILIKE.
    """
    if not query or not query.strip():
        return []

    query = query.strip()

    # 1. Точное совпадение кошелька
    wallet = (
        client.table("wallets")
        .select("candidate_id")
        .or_(f"wallet_address.eq.{query},name_service.eq.{query}")
        .limit(1)
        .execute()
    )
    if wallet.data:
        return [wallet.data[0]["candidate_id"]]

    # 2. Точное совпадение username в profiles
    profile = (
        client.table("profiles")
        .select("candidate_id")
        .eq("username", query)
        .limit(1)
        .execute()
    )
    if profile.data:
        return [profile.data[0]["candidate_id"]]

    # 3. Точное совпадение main_username
    candidate = (
        client.table("candidates")
        .select("id")
        .eq("main_username", query)
        .limit(1)
        .execute()
    )
    if candidate.data:
        return [candidate.data[0]["id"]]

    # 4. Синоним
    alias = (
        client.table("known_aliases")
        .select("candidate_id")
        .eq("alias", query.lower())
        .limit(1)
        .execute()
    )
    if alias.data:
        return [alias.data[0]["candidate_id"]]

    # 5. Нечёткий поиск через представление
    try:
        fuzzy = client.rpc(
            "search_candidates_fuzzy",
            {"search_query": query, "limit_rows": limit},
        ).execute()
        if fuzzy.data:
            return [int(row["candidate_id"]) for row in fuzzy.data]
    except Exception:
        pass  # если функция ещё не создана, fallback на ILIKE

    # 6. ILIKE fallback
    ids = []
    # candidates.main_username
    resp = (
        client.table("candidates")
        .select("id")
        .ilike("main_username", f"%{query}%")
        .limit(limit)
        .execute()
    )
    for r in (resp.data or []):
        ids.append(int(r["id"]))

    if len(ids) < limit:
        resp = (
            client.table("candidates")
            .select("id")
            .ilike("display_name", f"%{query}%")
            .limit(limit)
            .execute()
        )
        for r in (resp.data or []):
            if int(r["id"]) not in ids:
                ids.append(int(r["id"]))

    if len(ids) < limit:
        resp = (
            client.table("profiles")
            .select("candidate_id")
            .ilike("username", f"%{query}%")
            .limit(limit)
            .execute()
        )
        for r in (resp.data or []):
            if int(r["candidate_id"]) not in ids:
                ids.append(int(r["candidate_id"]))

    if len(ids) < limit:
        resp = (
            client.table("contacts")
            .select("candidate_id")
            .ilike("value", f"%{query}%")
            .limit(limit)
            .execute()
        )
        for r in (resp.data or []):
            if int(r["candidate_id"]) not in ids:
                ids.append(int(r["candidate_id"]))

    if len(ids) < limit:
        resp = (
            client.table("wallets")
            .select("candidate_id")
            .or_(
                f"wallet_address.ilike.%{query}%,name_service.ilike.%{query}%"
            )
            .limit(limit)
            .execute()
        )
        for r in (resp.data or []):
            if int(r["candidate_id"]) not in ids:
                ids.append(int(r["candidate_id"]))

    return ids[:limit]