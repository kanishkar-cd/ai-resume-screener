from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import Settings
from app.services.zoho_recruit_service import (
    ZohoAttachment,
    ZohoRecruitClient,
    ZohoRecruitException,
    ZohoRecruitNotConfiguredException,
)

API = "https://recruit.zoho.in/recruit/v2"


def _settings(**overrides) -> Settings:
    values = {
        "ZOHO_CLIENT_ID": "client-id",
        "ZOHO_CLIENT_SECRET": "client-secret",
        "ZOHO_REFRESH_TOKEN": "refresh-token",
        "ZOHO_MAX_RETRIES": 2,
        **overrides,
    }
    return Settings(**values)


class FakeZoho:
    """Minimal Zoho accounts + Recruit API used through httpx.MockTransport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.candidates = [
            {"id": "101", "Candidate_ID": "ZR_1", "First_Name": "Priya", "Last_Name": "Sharma",
             "Email": "priya@example.com", "Mobile": "+91 9876543210", "Source": "Naukri",
             "Modified_Time": "2026-10-01T10:00:00+05:30"},
            {"id": "102", "Full_Name": "Arun K", "Email": "arun@example.com",
             "Modified_Time": "2026-10-02T10:00:00+05:30"},
            {"id": "103", "Full_Name": "No Resume", "Modified_Time": "2026-10-03T10:00:00+05:30"},
        ]
        self.attachments = {
            "101": [
                {"id": "a1", "File_Name": "cover_letter.pdf", "Modified_Time": "2026-10-01T10:00:00+05:30"},
                {"id": "a2", "File_Name": "Priya_old.pdf", "Category": {"name": "Resume", "id": "9"},
                 "Modified_Time": "2026-09-01T10:00:00+05:30"},
                {"id": "a3", "File_Name": "Priya_updated.docx", "Category": {"name": "Resume", "id": "9"},
                 "Modified_Time": "2026-10-01T09:00:00+05:30", "Size": "2048"},
            ],
            "102": [{"id": "b1", "File_Name": "arun_resume.pdf", "Modified_Time": "2026-10-02T10:00:00+05:30"}],
            "103": [{"id": "c1", "File_Name": "photo.png"}],
        }
        self.per_page = 2
        self.fail_next: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/oauth/v2/token":
            self.token_calls += 1
            return httpx.Response(200, json={"access_token": f"token-{self.token_calls}", "expires_in": 3600})
        if self.fail_next:
            return self.fail_next.pop(0)
        assert request.headers["Authorization"].startswith("Zoho-oauthtoken token-")
        parts = request.url.path.split("/recruit/v2/")[1].split("/")
        if parts == ["Candidates"]:
            page = int(request.url.params["page"])
            since = request.headers.get("If-Modified-Since")
            rows = [c for c in self.candidates if not since or c["Modified_Time"] > since]
            if not rows:
                return httpx.Response(304)
            chunk = rows[(page - 1) * self.per_page: page * self.per_page]
            more = page * self.per_page < len(rows)
            return httpx.Response(200, json={"data": chunk, "info": {"page": page, "more_records": more}})
        if len(parts) == 3 and parts[2] == "Attachments":
            return httpx.Response(200, json={"data": self.attachments[parts[1]], "info": {"more_records": False}})
        if len(parts) == 4:
            return httpx.Response(
                200, content=f"file:{parts[3]}".encode(),
                headers={"Content-Type": "application/octet-stream",
                         "Content-Disposition": f'attachment; filename="{parts[3]}.bin"'},
            )
        return httpx.Response(404, json={"code": "INVALID_URL_PATTERN"})


@pytest.fixture
def fake() -> FakeZoho:
    return FakeZoho()


@pytest.fixture
def client(fake: FakeZoho, monkeypatch: pytest.MonkeyPatch) -> ZohoRecruitClient:
    async def no_sleep(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(ZohoRecruitClient, "_backoff", staticmethod(no_sleep))
    return ZohoRecruitClient(_settings(), transport=httpx.MockTransport(fake.handler))


@pytest.mark.asyncio
async def test_fetches_resumes_across_pages_and_picks_latest_resume(client: ZohoRecruitClient, fake: FakeZoho) -> None:
    result = await client.fetch_candidate_resumes()

    assert result.candidates_seen == 3
    assert [r.candidate_id for r in result.resumes] == ["101", "102"]
    priya, arun = result.resumes
    # Newest attachment in the "Resume" category wins over an older resume and a cover letter.
    assert priya.attachment.id == "a3"
    assert priya.file_name == "Priya_updated.docx"
    assert priya.content == b"file:a3"
    assert priya.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert (priya.full_name, priya.email, priya.phone, priya.source) == (
        "Priya Sharma", "priya@example.com", "+91 9876543210", "Naukri")
    # Without a category, a PDF named like a resume is chosen.
    assert arun.attachment.id == "b1" and arun.content_type == "application/pdf"
    assert result.skipped == [{"candidate_id": "103", "reason": "no PDF/DOCX resume attached"}]
    # One token for the whole run; two candidate pages.
    assert fake.token_calls == 1
    assert [r.url.params.get("page") for r in fake.requests if r.url.path.endswith("/Candidates")] == ["1", "2"]


@pytest.mark.asyncio
async def test_modified_since_sends_header_and_handles_not_modified(client: ZohoRecruitClient, fake: FakeZoho) -> None:
    since = datetime(2026, 10, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    result = await client.fetch_candidate_resumes(modified_since=since)

    assert [r.candidate_id for r in result.resumes] == ["102"]
    header = next(r for r in fake.requests if r.url.path.endswith("/Candidates")).headers["If-Modified-Since"]
    assert header == "2026-10-01T12:00:00+05:30"

    later = datetime(2026, 12, 1, tzinfo=timezone.utc)
    nothing = await client.fetch_candidate_resumes(modified_since=later)
    assert nothing.candidates_seen == 0 and nothing.resumes == []


@pytest.mark.asyncio
async def test_limit_stops_after_n_candidates(client: ZohoRecruitClient) -> None:
    result = await client.fetch_candidate_resumes(limit=1)
    assert result.candidates_seen == 1
    assert [r.candidate_id for r in result.resumes] == ["101"]


@pytest.mark.asyncio
async def test_401_refreshes_token_once_and_retries(client: ZohoRecruitClient, fake: FakeZoho) -> None:
    fake.fail_next = [httpx.Response(401, json={"code": "INVALID_TOKEN"})]
    attachments = await client.list_attachments("102")

    assert [a.id for a in attachments] == ["b1"]
    assert fake.token_calls == 2


@pytest.mark.asyncio
async def test_rate_limit_and_server_errors_are_retried(client: ZohoRecruitClient, fake: FakeZoho) -> None:
    fake.fail_next = [httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(503)]
    attachments = await client.list_attachments("102")
    assert [a.id for a in attachments] == ["b1"]


@pytest.mark.asyncio
async def test_gives_up_after_max_retries(client: ZohoRecruitClient, fake: FakeZoho) -> None:
    fake.fail_next = [httpx.Response(500)] * 3
    with pytest.raises(ZohoRecruitException):
        await client.list_attachments("102")


@pytest.mark.asyncio
async def test_failed_candidate_is_skipped_not_fatal(client: ZohoRecruitClient, fake: FakeZoho) -> None:
    fake.attachments["101"] = [{"id": "x", "File_Name": "resume.pdf"}]
    original = fake.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Candidates/101/Attachments/x"):
            return httpx.Response(400, json={"code": "INVALID_DATA"})
        return original(request)

    client._transport = httpx.MockTransport(handler)
    result = await client.fetch_candidate_resumes()

    assert [r.candidate_id for r in result.resumes] == ["102"]
    assert {"candidate_id": "101", "reason": "Zoho Recruit GET Candidates/101/Attachments/x failed: INVALID_DATA"} in result.skipped


@pytest.mark.asyncio
async def test_invalid_refresh_token_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "invalid_code"})

    client = ZohoRecruitClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ZohoRecruitException, match="invalid_code"):
        await client.list_attachments("101")


@pytest.mark.asyncio
async def test_missing_credentials_raise_not_configured() -> None:
    client = ZohoRecruitClient(_settings(ZOHO_REFRESH_TOKEN=None))
    assert client.configured is False
    with pytest.raises(ZohoRecruitNotConfiguredException):
        await client.fetch_candidate_resumes()


def test_select_resume_ignores_unsupported_files() -> None:
    files = [ZohoAttachment("1", "photo.jpg", None, None, None), ZohoAttachment("2", "old.doc", None, None, "Resume")]
    assert ZohoRecruitClient.select_resume(files) is None
