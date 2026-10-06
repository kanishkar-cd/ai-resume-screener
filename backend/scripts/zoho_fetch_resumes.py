"""Zoho Recruit helper: one-time refresh-token setup and a manual resume fetch.

Setup (once, by someone with Zoho admin access):
  1. https://api-console.zoho.in -> Add Client -> "Self Client" (or Server-based).
  2. Put the client id/secret in backend/.env as ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET.
  3. Self Client -> Generate Code with scope:
       ZohoRECRUIT.modules.candidate.READ,ZohoRECRUIT.modules.attachments.all
     (the grant code is valid for a few minutes).
  4. python scripts/zoho_fetch_resumes.py exchange-code <GRANT_CODE>
     and copy the printed refresh token into .env as ZOHO_REFRESH_TOKEN.

Fetch (writes resumes to a folder; no database changes):
  python scripts/zoho_fetch_resumes.py fetch --limit 5 --out zoho_resumes
  python scripts/zoho_fetch_resumes.py fetch --since 2026-10-01T00:00:00+05:30
"""

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.zoho_recruit_service import ZohoRecruitClient, ZohoRecruitException  # noqa: E402


async def exchange_code(code: str) -> int:
    settings = get_settings()
    if not (settings.ZOHO_CLIENT_ID and settings.ZOHO_CLIENT_SECRET):
        print("Set ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET in .env first.")
        return 1
    async with httpx.AsyncClient(timeout=settings.ZOHO_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{settings.ZOHO_ACCOUNTS_URL.rstrip('/')}/oauth/v2/token",
            params={
                "grant_type": "authorization_code",
                "client_id": settings.ZOHO_CLIENT_ID,
                "client_secret": settings.ZOHO_CLIENT_SECRET,
                "code": code,
            },
        )
    body = response.json()
    if "refresh_token" not in body:
        print(f"Exchange failed: {body.get('error') or body}")
        print("Grant codes expire within minutes and work once; generate a new one and retry.")
        return 1
    print("Add this line to backend/.env (keep it secret):")
    print(f"ZOHO_REFRESH_TOKEN={body['refresh_token']}")
    return 0


async def fetch(since: str | None, limit: int | None, out: Path) -> int:
    client = ZohoRecruitClient()
    modified_since = datetime.fromisoformat(since) if since else None
    try:
        result = await client.fetch_candidate_resumes(modified_since, limit=limit)
    except ZohoRecruitException as exc:
        print(f"Zoho fetch failed: {exc.message}")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for resume in result.resumes:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", resume.file_name)
        (out / f"{resume.candidate_id}_{safe_name}").write_bytes(resume.content)
        print(f"{resume.candidate_id:>20}  {resume.full_name or '-':30.30}  {resume.source or '-':12.12}  "
              f"{resume.modified_time or '-':25}  {resume.file_name}")
    for skipped in result.skipped:
        print(f"{skipped['candidate_id']:>20}  SKIPPED: {skipped['reason']}")
    print(f"\nCandidates: {result.candidates_seen}  resumes saved: {len(result.resumes)}  "
          f"skipped: {len(result.skipped)}  -> {out.resolve()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    exchange = sub.add_parser("exchange-code", help="Swap a Self Client grant code for a refresh token")
    exchange.add_argument("code")
    fetch_cmd = sub.add_parser("fetch", help="Download candidate resumes to a folder")
    fetch_cmd.add_argument("--since", help="ISO datetime, e.g. 2026-10-01T00:00:00+05:30")
    fetch_cmd.add_argument("--limit", type=int, help="Stop after this many candidates")
    fetch_cmd.add_argument("--out", type=Path, default=Path("zoho_resumes"))
    args = parser.parse_args()
    if args.command == "exchange-code":
        return asyncio.run(exchange_code(args.code))
    return asyncio.run(fetch(args.since, args.limit, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
