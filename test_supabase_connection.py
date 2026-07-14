#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from supabase import create_client


def load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        print(".env not found")
        return

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def main() -> None:
    load_env_file()

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()

    print("=" * 72)
    print("Testing Supabase connection")
    print("=" * 72)
    print(f"SUPABASE_URL present: {bool(url)}")
    print(f"SUPABASE_KEY present: {bool(key)}")
    print("=" * 72)

    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_KEY missing in .env")

    client = create_client(url, key)

    payload = {
        "job_type": "connection_test",
        "query": "hello from new pycharm project",
        "status": "done",
        "result_count": 1,
    }

    insert_response = (
        client
        .table("parser_jobs")
        .insert(payload)
        .execute()
    )

    print("Insert response:")
    print(insert_response.data)

    select_response = (
        client
        .table("parser_jobs")
        .select("*")
        .eq("job_type", "connection_test")
        .limit(5)
        .execute()
    )

    print("Select response:")
    print(select_response.data)

    print("=" * 72)
    print("Supabase connection OK")
    print("=" * 72)


if __name__ == "__main__":
    main()