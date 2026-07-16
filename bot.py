#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mirae Telegram Bot MVP.

Commands:
    /start
    /help
    /top
    /search nickname
    /profile 44
    /full 44
    /resolve https://x.com/somehandle
"""

import os
import re
import sys
import html
import asyncio
import subprocess
from typing import Any, Dict, List

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from db_supabase import (
    get_supabase_client,
    clean_text,
    search_candidate_ids,
)

MAX_MESSAGE_LEN = 3900


def load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_env_file()


def esc(value: Any) -> str:
    return html.escape(clean_text(value))


def short(value: Any, max_len: int = 600) -> str:
    text = clean_text(value)

    if len(text) <= max_len:
        return text

    return text[:max_len].rstrip() + "..."


def chunk_text(text: str, max_len: int = MAX_MESSAGE_LEN) -> List[str]:
    chunks = []

    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)

        if cut == -1:
            cut = max_len

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)

    return chunks


async def reply_long(update: Update, text: str) -> None:
    for chunk in chunk_text(text):
        await update.message.reply_text(
            chunk,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def fetch_candidate(client, candidate_id: int) -> Dict[str, Any]:
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


def fetch_evidence(client, candidate_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    response = (
        client
        .table("evidence")
        .select("*")
        .eq("candidate_id", candidate_id)
        .order("confidence", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


def get_top_candidate_ids(client, limit: int = 10) -> List[int]:
    response = (
        client
        .table("candidates")
        .select("id")
        .order("overall_trust_score", desc=True)
        .limit(limit)
        .execute()
    )

    return [int(item["id"]) for item in response.data or []]


def format_short_profile(client, candidate_id: int) -> str:
    candidate = fetch_candidate(client, candidate_id)

    if not candidate:
        return f"Candidate not found: {candidate_id}"

    profiles = fetch_profiles(client, candidate_id)

    lines = []

    lines.append(f"<b>Candidate ID:</b> {esc(candidate.get('id'))}")
    lines.append(f"<b>Username:</b> {esc(candidate.get('main_username'))}")
    lines.append(f"<b>Display name:</b> {esc(candidate.get('display_name'))}")
    lines.append(f"<b>Status:</b> {esc(candidate.get('status'))}")
    lines.append("")
    lines.append(f"<b>Overall trust:</b> {esc(candidate.get('overall_trust_score'))}/100")
    lines.append(f"<b>Relevance:</b> {esc(candidate.get('relevance_score'))}/100")
    lines.append(f"<b>Identity:</b> {esc(candidate.get('identity_score'))}/100")
    lines.append(f"<b>Wallet score:</b> {esc(candidate.get('wallet_score'))}/100")
    lines.append(f"<b>Contact score:</b> {esc(candidate.get('contact_score'))}/100")

    bio = clean_text(candidate.get("bio"))

    if bio:
        lines.append("")
        lines.append("<b>Bio:</b>")
        lines.append(esc(short(bio, 700)))

    lines.append("")
    lines.append("<b>Profiles:</b>")

    if profiles:
        for profile in profiles[:5]:
            platform = esc(profile.get("platform"))
            username = esc(profile.get("username"))
            profile_url = esc(profile.get("profile_url"))
            source_url = esc(profile.get("source_url"))
            confidence = esc(profile.get("confidence"))

            lines.append(f"• <b>{platform}</b>: {username}")
            if profile_url:
                lines.append(f"  profile: {profile_url}")
            if source_url:
                lines.append(f"  source: {source_url}")
            lines.append(f"  confidence: {confidence}")
    else:
        lines.append("• none")

    lines.append("")
    lines.append(f"Full evidence: <code>/full {candidate_id}</code>")

    return "\n".join(lines)


def format_full_profile(client, candidate_id: int) -> str:
    candidate = fetch_candidate(client, candidate_id)

    if not candidate:
        return f"Candidate not found: {candidate_id}"

    profiles = fetch_profiles(client, candidate_id)
    contacts = fetch_contacts(client, candidate_id)
    wallets = fetch_wallets(client, candidate_id)
    evidence = fetch_evidence(client, candidate_id, limit=12)

    text = format_short_profile(client, candidate_id)

    lines = [text, ""]

    lines.append("<b>Contacts:</b>")

    useful_contacts = sorted(
        contacts,
        key=lambda item: int(item.get("confidence") or 0),
        reverse=True,
    )

    if useful_contacts:
        for contact in useful_contacts[:10]:
            lines.append(
                f"• {esc(contact.get('contact_type'))}: "
                f"{esc(contact.get('value'))} "
                f"| confidence={esc(contact.get('confidence'))}"
            )
            if contact.get("evidence_url"):
                lines.append(f"  evidence: {esc(contact.get('evidence_url'))}")

        if len(useful_contacts) > 10:
            lines.append(f"• hidden {len(useful_contacts) - 10} more contacts")
    else:
        lines.append("• none")

    lines.append("")
    lines.append("<b>Wallets:</b>")

    if wallets:
        for wallet in wallets[:10]:
            value = wallet.get("wallet_address") or wallet.get("name_service")
            lines.append(
                f"• {esc(wallet.get('wallet_type'))}: "
                f"{esc(value)} "
                f"| chain={esc(wallet.get('chain'))} "
                f"| confidence={esc(wallet.get('confidence'))}"
            )
            if wallet.get("evidence_url"):
                lines.append(f"  evidence: {esc(wallet.get('evidence_url'))}")
            if wallet.get("evidence_text"):
                lines.append(f"  text: {esc(short(wallet.get('evidence_text'), 250))}")

        if len(wallets) > 10:
            lines.append(f"• hidden {len(wallets) - 10} more wallets")
    else:
        lines.append("• none")

    lines.append("")
    lines.append("<b>Evidence:</b>")

    if evidence:
        for item in evidence[:10]:
            lines.append(
                f"• {esc(item.get('entity_type'))}: "
                f"{esc(item.get('entity_value'))} "
                f"| confidence={esc(item.get('confidence'))}"
            )
            if item.get("source_url"):
                lines.append(f"  source: {esc(item.get('source_url'))}")
            if item.get("evidence_text"):
                lines.append(f"  text: {esc(short(item.get('evidence_text'), 250))}")
    else:
        lines.append("• none")

    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = """
<b>Mirae Web3 Trust Bot</b>

Commands:

<code>/top</code>
Show top candidates.

<code>/search nickname</code>
Search by username, contact, wallet, ENS or .sol.

<code>/profile 44</code>
Show short candidate card.

<code>/full 44</code>
Show contacts, wallets and evidence.

<code>/resolve https://x.com/somehandle</code>
Resolve X/ENS/Farcaster/Lens/wallet via public identity signals.
""".strip()

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = get_supabase_client()

    candidate_ids = await asyncio.to_thread(
        get_top_candidate_ids,
        client,
        10,
    )

    if not candidate_ids:
        await update.message.reply_text("No candidates found.")
        return

    lines = ["<b>Top candidates</b>", ""]

    for candidate_id in candidate_ids:
        candidate = fetch_candidate(client, candidate_id)

        if not candidate:
            continue

        lines.append(
            f"#{esc(candidate.get('id'))} "
            f"{esc(candidate.get('main_username'))} "
            f"| trust={esc(candidate.get('overall_trust_score'))} "
            f"| status={esc(candidate.get('status'))}"
        )
        lines.append(f"Open: <code>/profile {candidate_id}</code>")
        lines.append("")

    await reply_long(update, "\n".join(lines))


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()

    if not query:
        await update.message.reply_text("Usage: /search nickname")
        return

    client = get_supabase_client()

    candidate_ids = await asyncio.to_thread(
        search_candidate_ids, client, query, 10
    )

    if not candidate_ids:
        await update.message.reply_text(f"No matches for: {query}")
        return

    lines = [f"<b>Search:</b> {esc(query)}", f"<b>Matches:</b> {len(candidate_ids)}", ""]

    for candidate_id in candidate_ids:
        candidate = fetch_candidate(client, candidate_id)

        if not candidate:
            continue

        lines.append(
            f"#{esc(candidate.get('id'))} "
            f"{esc(candidate.get('main_username'))} "
            f"| trust={esc(candidate.get('overall_trust_score'))} "
            f"| status={esc(candidate.get('status'))}"
        )
        lines.append(f"Open: <code>/profile {candidate_id}</code>")
        lines.append("")

    await reply_long(update, "\n".join(lines))


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /profile 44")
        return

    try:
        candidate_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Candidate ID must be a number.")
        return

    client = get_supabase_client()

    text = await asyncio.to_thread(
        format_short_profile,
        client,
        candidate_id,
    )

    await reply_long(update, text)


async def full_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /full 44")
        return

    try:
        candidate_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Candidate ID must be a number.")
        return

    client = get_supabase_client()

    text = await asyncio.to_thread(
        format_full_profile,
        client,
        candidate_id,
    )

    await reply_long(update, text)


def run_resolve_subprocess(identity: str) -> str:
    process = subprocess.run(
        [sys.executable, "resolve_identity.py", identity],
        capture_output=True,
        text=True,
        timeout=90,
    )

    output = ""

    if process.stdout:
        output += process.stdout

    if process.stderr:
        output += "\nSTDERR:\n" + process.stderr

    return output.strip()


def parse_candidate_id_from_resolve_output(output: str) -> int:
    patterns = [
        r"candidate_id:\s*(\d+)",
        r"candidate_id=(\d+)",
        r"Saving to candidate_id=(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, output)

        if match:
            return int(match.group(1))

    return 0


def run_recalculate_subprocess(candidate_id: int) -> str:
    process = subprocess.run(
        [sys.executable, "recalculate_scores.py", "--id", str(candidate_id)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    return (process.stdout or "") + ("\n" + process.stderr if process.stderr else "")


async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    identity = " ".join(context.args).strip()

    if not identity:
        await update.message.reply_text("Usage: /resolve https://x.com/somehandle")
        return

    await update.message.reply_text("Resolving identity...")

    output = await asyncio.to_thread(
        run_resolve_subprocess,
        identity,
    )

    candidate_id = parse_candidate_id_from_resolve_output(output)

    if not candidate_id:
        preview = short(output, 2500) if output else "No output."
        await reply_long(
            update,
            "<b>Resolve finished, but candidate_id was not found.</b>\n\n"
            f"<pre>{esc(preview)}</pre>",
        )
        return

    await asyncio.to_thread(
        run_recalculate_subprocess,
        candidate_id,
    )

    client = get_supabase_client()

    profile_text = await asyncio.to_thread(
        format_short_profile,
        client,
        candidate_id,
    )

    await reply_long(update, profile_text)

async def resolve_full_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        identity = " ".join(context.args).strip()

        if not identity:
            await update.message.reply_text("Usage: /resolve_full https://x.com/somehandle")
            return

        await update.message.reply_text("Resolving identity with full evidence...")

        output = await asyncio.to_thread(
            run_resolve_subprocess,
            identity,
        )

        candidate_id = parse_candidate_id_from_resolve_output(output)

        if not candidate_id:
            preview = short(output, 2500) if output else "No output."
            await reply_long(
                update,
                "<b>Resolve finished, but candidate_id was not found.</b>\n\n"
                f"<pre>{esc(preview)}</pre>",
            )
            return

        await asyncio.to_thread(
            run_recalculate_subprocess,
            candidate_id,
        )

        client = get_supabase_client()

        profile_text = await asyncio.to_thread(
            format_full_profile,
            client,
            candidate_id,
        )

        await reply_long(update, profile_text)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("full", full_command))
    app.add_handler(CommandHandler("resolve", resolve_command))
    app.add_handler(CommandHandler("resolve_full", resolve_full_command))

    print("=" * 90)
    print("Mirae Telegram Bot is running")
    print("=" * 90)

    app.run_polling()


if __name__ == "__main__":
    main()