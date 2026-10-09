"""Zoho Recruit helper: one-time refresh-token setup, job opening listing, and resume fetching.

Setup (once, by someone with Zoho admin access):
  1. https://api-console.zoho.in -> Add Client -> "Self Client" (or Server-based).
  2. Put the client id/secret in backend/.env as ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET.
  3. Self Client -> Generate Code with scopes:
       ZohoRecruit.modules.jobopening.READ,ZohoRecruit.modules.candidate.READ,ZohoRecruit.modules.attachment.READ
     (the grant code is valid for a few minutes).
  4. python scripts/zoho_fetch_resumes.py exchange-code <GRANT_CODE>
     and copy the printed refresh token into .env as ZOHO_REFRESH_TOKEN.

Usage Examples:
  # List open job positions / JDs
  python scripts/zoho_fetch_resumes.py list-jobs

  # Fetch JD and all applied candidate resumes for a specific job opening:
  python scripts/zoho_fetch_resumes.py fetch-job --job-id 58392000000123456 --out zoho_jobs

  # Global candidate resume fetch:
  python scripts/zoho_fetch_resumes.py fetch --limit 5 --out zoho_resumes
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.zoho_recruit_service import (  # noqa: E402
    ZohoRecruitClient,
    ZohoRecruitException,
)


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


async def list_jobs(status: str | None, limit: int | None) -> int:
    client = ZohoRecruitClient()
    try:
        count = 0
        print(f"{'Job ID':<22} {'Posting Title':<35} {'Status':<15} {'Department':<20} {'Skills'}")
        print("-" * 110)
        async for job in client.iter_job_openings(status=status):
            skills = (job.required_skills or "-").replace("\n", " ")
            print(
                f"{job.id:<22} {job.posting_title[:33]:<35} {job.job_status or '-':<15} "
                f"{(job.department or '-')[:18]:<20} {skills[:35]}"
            )
            count += 1
            if limit and count >= limit:
                break
        print(f"\nTotal Job Openings: {count}")
    except ZohoRecruitException as exc:
        print(f"Failed to list job openings: {exc.message}")
        return 1
    return 0


async def fetch_job(job_id: str, limit: int | None, out: Path) -> int:
    client = ZohoRecruitClient()
    try:
        result = await client.fetch_job_with_applicant_resumes(job_id, limit=limit)
    except ZohoRecruitException as exc:
        print(f"Zoho fetch-job failed: {exc.message}")
        return 1

    job_dir = out / f"{job_id}_{re.sub(r'[^A-Za-z0-9._-]+', '_', result.job_opening.posting_title)}"
    resumes_dir = job_dir / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)

    # Save Job Description & metadata
    jd_file = job_dir / "job_description.txt"
    jd_content = f"Posting Title: {result.job_opening.posting_title}\n"
    jd_content += f"Job ID: {result.job_opening.id} (Code: {result.job_opening.job_opening_id or '-'})\n"
    jd_content += f"Status: {result.job_opening.job_status or '-'}\n"
    jd_content += f"Department: {result.job_opening.department or '-'}\n"
    jd_content += f"Target Date: {result.job_opening.target_date or '-'}\n"
    jd_content += f"Required Skills:\n{result.job_opening.required_skills or '-'}\n\n"
    jd_content += f"Job Description:\n{result.job_opening.job_description or '-'}\n"
    jd_file.write_text(jd_content, encoding="utf-8")

    meta_file = job_dir / "job_details.json"
    meta_file.write_text(json.dumps(result.job_opening.raw_data, indent=2), encoding="utf-8")

    print(f"\n[JOB OPENING]: {result.job_opening.posting_title} (ID: {job_id})")
    print(f"JD saved to: {jd_file.resolve()}\n")
    print(f"{'Candidate ID':<20} {'Name':<30} {'Source':<12} {'File Name'}")
    print("-" * 90)

    for resume in result.resumes:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", resume.file_name)
        (resumes_dir / f"{resume.candidate_id}_{safe_name}").write_bytes(resume.content)
        print(
            f"{resume.candidate_id:<20} {(resume.full_name or '-'):<30.30} "
            f"{(resume.source or '-'):<12.12} {resume.file_name}"
        )

    for skipped in result.skipped:
        print(f"{skipped['candidate_id']:<20} SKIPPED: {skipped['reason']}")

    print(
        f"\nApplicants: {result.candidates_seen} | Resumes Downloaded: {len(result.resumes)} | "
        f"Skipped: {len(result.skipped)} -> {resumes_dir.resolve()}"
    )
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
        print(
            f"{resume.candidate_id:>20}  {resume.full_name or '-':30.30}  {resume.source or '-':12.12}  "
            f"{resume.modified_time or '-':25}  {resume.file_name}"
        )
    for skipped in result.skipped:
        print(f"{skipped['candidate_id']:>20}  SKIPPED: {skipped['reason']}")
    print(
        f"\nCandidates: {result.candidates_seen}  resumes saved: {len(result.resumes)}  "
        f"skipped: {len(result.skipped)}  -> {out.resolve()}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    # exchange-code
    exchange = sub.add_parser("exchange-code", help="Swap a Self Client grant code for a refresh token")
    exchange.add_argument("code", help="Zoho OAuth grant authorization code")

    # list-jobs
    list_jobs_cmd = sub.add_parser("list-jobs", help="List Job Openings (JDs) in Zoho Recruit")
    list_jobs_cmd.add_argument("--status", help="Filter by job status, e.g. 'In-progress', 'Open'")
    list_jobs_cmd.add_argument("--limit", type=int, help="Stop after this many job openings")

    # fetch-job
    fetch_job_cmd = sub.add_parser("fetch-job", help="Fetch JD and applicant resumes for a specific Job Opening")
    fetch_job_cmd.add_argument("--job-id", required=True, help="Zoho Job Opening ID")
    fetch_job_cmd.add_argument("--limit", type=int, help="Limit number of candidate resumes to download")
    fetch_job_cmd.add_argument("--out", type=Path, default=Path("zoho_jobs"), help="Directory to save JD and resumes")

    # fetch (global candidates)
    fetch_cmd = sub.add_parser("fetch", help="Download candidate resumes globally to a folder")
    fetch_cmd.add_argument("--since", help="ISO datetime, e.g. 2026-10-01T00:00:00+05:30")
    fetch_cmd.add_argument("--limit", type=int, help="Stop after this many candidates")
    fetch_cmd.add_argument("--out", type=Path, default=Path("zoho_resumes"))

    args = parser.parse_args()
    if args.command == "exchange-code":
        return asyncio.run(exchange_code(args.code))
    if args.command == "list-jobs":
        return asyncio.run(list_jobs(args.status, args.limit))
    if args.command == "fetch-job":
        return asyncio.run(fetch_job(args.job_id, args.limit, args.out))
    if args.command == "fetch":
        return asyncio.run(fetch(args.since, args.limit, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
