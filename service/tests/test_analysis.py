"""Investigator-assistance findings.

Findings are review prompts for a human, so each one has to carry the
observation it rests on. These tests check that the rules fire on the right
measurements and that the endpoint is fully useful with no AI configured.
"""

from datetime import datetime, timedelta, timezone

import pytest

from models.common import Confidence, Vendor, VendorFamily
from routers import agent
from tests import factories

SUMMARY = "/api/analysis/summary"


def summarize(api_client, device, index=None, narrate=True):
    payload = {"device": device.model_dump(mode="json"), "narrate": narrate}
    if index is not None:
        payload["index"] = index.model_dump(mode="json")
    response = api_client.post(SUMMARY, json=payload)
    assert response.status_code == 200
    return response.json()


def titles(body):
    return [finding["title"] for finding in body["data"]["findings"]]


def by_category(body, category):
    return [f for f in body["data"]["findings"] if f["category"] == category]


@pytest.fixture(autouse=True)
def no_ai_credentials(monkeypatch):
    """Pin the AI configuration so the result never depends on the environment."""
    monkeypatch.setattr(agent, "AI_ENABLED", False)
    monkeypatch.setattr(agent, "NVIDIA_API_KEY", "")


class TestClockFindings:
    def test_drift_beyond_an_hour_is_critical(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=7200.0))

        clock = by_category(body, "clock")[0]
        assert clock["severity"] == "CRITICAL"
        assert "7200s ahead of" in clock["title"]
        assert clock["observation"] == "drift_seconds = 7200.00"

    def test_drift_beyond_five_minutes_is_a_warning(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=-600.0))

        clock = by_category(body, "clock")[0]
        assert clock["severity"] == "WARNING"
        assert "600s behind" in clock["title"]

    def test_a_small_offset_is_recorded_but_not_escalated(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=12.0))

        clock = by_category(body, "clock")[0]
        assert clock["severity"] == "INFO"

    def test_an_unmeasured_clock_is_a_warning_in_its_own_right(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=None))

        clock = by_category(body, "clock")
        assert len(clock) == 1
        assert clock[0]["severity"] == "WARNING"
        assert "could not be measured" in clock[0]["title"]

    def test_disabled_ntp_is_reported_alongside_the_drift(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=10.0, ntp_enabled=False))

        assert "NTP synchronisation is disabled" in titles(body)

    def test_enabled_ntp_produces_no_finding(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=10.0, ntp_enabled=True))

        assert "NTP synchronisation is disabled" not in titles(body)


class TestStorageFindings:
    def test_a_failing_disk_is_critical(self, api_client):
        body = summarize(api_client, factories.device(storage=[factories.failed_disk()]))

        storage = by_category(body, "storage")
        assert storage[0]["severity"] == "CRITICAL"
        assert "smartFailed" in storage[0]["title"]
        assert "Image this disk" in storage[0]["detail"]

    def test_a_nearly_full_disk_warns_about_overwriting(self, api_client):
        body = summarize(api_client, factories.device(storage=[factories.nearly_full_disk()]))

        storage = by_category(body, "storage")
        assert storage[0]["severity"] == "WARNING"
        assert "99.0% full" in storage[0]["title"]
        assert storage[0]["observation"] == "free 10000000000 of 1000000000000 bytes"

    def test_a_healthy_disk_produces_no_storage_finding(self, api_client):
        body = summarize(api_client, factories.device(storage=[factories.healthy_disk()]))

        assert by_category(body, "storage") == []

    def test_no_enumerated_storage_is_itself_a_finding(self, api_client):
        body = summarize(api_client, factories.device(storage=[]))

        storage = by_category(body, "storage")
        assert storage[0]["title"] == "No storage devices were enumerated"

    def test_several_disks_are_assessed_independently(self, api_client):
        body = summarize(
            api_client,
            factories.device(
                storage=[
                    factories.healthy_disk(),
                    factories.failed_disk(),
                    factories.nearly_full_disk(),
                ]
            ),
        )

        storage = by_category(body, "storage")
        assert len(storage) == 2
        assert {f["severity"] for f in storage} == {"CRITICAL", "WARNING"}


class TestIdentityFindings:
    def test_a_probable_attribution_is_flagged(self, api_client):
        body = summarize(
            api_client,
            factories.device(
                confidence=Confidence.PROBABLE,
                vendor=Vendor.GODREJ,
                family=VendorFamily.XIONGMAI,
            ),
        )

        identity = by_category(body, "identity")
        assert identity[0]["title"] == "Vendor attribution is PROBABLE, not confirmed"
        assert identity[0]["observation"] == "vendor=GODREJ, family=XIONGMAI"

    def test_a_confirmed_attribution_is_not_flagged(self, api_client):
        body = summarize(api_client, factories.device(confidence=Confidence.CONFIRMED))

        assert by_category(body, "identity") == []

    def test_a_missing_serial_number_weakens_the_chain_of_custody(self, api_client):
        body = summarize(api_client, factories.device(serial_number=None))

        identity = by_category(body, "identity")
        assert identity[0]["title"] == "Recorder reported no serial number"
        assert identity[0]["severity"] == "WARNING"


class TestIndexFindings:
    def test_gaps_are_reported_with_the_longest_one_quantified(self, api_client):
        body = summarize(api_client, factories.device(), factories.index_with_gap())

        index_findings = by_category(body, "index")
        gap = next(f for f in index_findings if "gap(s)" in f["title"])
        assert gap["severity"] == "WARNING"
        assert "Channel 1 has 1 gap(s)" in gap["title"]
        assert "longest gap 1800s" in gap["observation"]
        assert "not proof of deletion" in gap["detail"]

    def test_overwritten_regions_are_reported(self, api_client):
        body = summarize(api_client, factories.device(), factories.index_with_gap())

        overwritten = next(
            f for f in by_category(body, "index") if "reused" in f["title"]
        )
        assert overwritten["observation"] == "max overwrite count 5"

    def test_truncation_is_reported(self, api_client):
        index = factories.index_with_gap()
        index.truncated = True

        body = summarize(api_client, factories.device(), index)

        assert "Recording index was truncated" in titles(body)

    def test_no_index_means_no_index_findings(self, api_client):
        body = summarize(api_client, factories.device())

        assert by_category(body, "index") == []

    def test_a_timeline_and_coverage_accompany_an_index(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=60.0), factories.index_with_gap())

        assert body["data"]["timeline"]["segment_count"] == 3
        assert body["data"]["timeline"]["drift_seconds_applied"] == 60.0
        assert body["data"]["coverage"]["1"]["segments"] == 3


class TestResponseShape:
    def test_findings_are_ordered_by_severity(self, api_client):
        device = factories.device(
            drift_seconds=7200.0,
            serial_number=None,
            confidence=Confidence.PROBABLE,
            storage=[factories.failed_disk()],
        )

        body = summarize(api_client, device)

        severities = [f["severity"] for f in body["data"]["findings"]]
        rank = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        assert severities == sorted(severities, key=lambda s: rank[s])

    def test_counts_match_the_findings_list(self, api_client):
        device = factories.device(
            drift_seconds=7200.0, serial_number=None, storage=[factories.failed_disk()]
        )

        body = summarize(api_client, device)

        counts = body["data"]["counts"]
        assert counts["CRITICAL"] >= 2
        assert sum(counts.values()) == len(body["data"]["findings"])
        assert body["message"] == f"Produced {len(body['data']['findings'])} finding(s)."

    def test_every_finding_states_the_observation_it_rests_on(self, api_client):
        device = factories.device(
            drift_seconds=7200.0, serial_number=None, storage=[factories.nearly_full_disk()]
        )

        body = summarize(api_client, device, factories.index_with_gap())

        assert body["data"]["findings"]
        for finding in body["data"]["findings"]:
            assert finding["observation"].strip()
            assert finding["detail"].strip()
            assert finding["severity"] in {"CRITICAL", "WARNING", "INFO"}

    def test_the_evidence_digest_ties_the_summary_to_its_source_material(self, api_client):
        device = factories.device()

        body = summarize(api_client, device)

        assert body["data"]["evidence_digest"] == device.evidence.combined_sha256

    def test_the_device_block_identifies_what_was_analysed(self, api_client):
        body = summarize(api_client, factories.device())

        assert body["data"]["device"] == {
            "vendor": "HIKVISION",
            "family": "HIKVISION",
            "model": "DS-7208HQHI-K1",
            "serial_number": "DS-7208-SERIAL",
        }


class TestNarration:
    def test_absent_credentials_are_stated_plainly(self, api_client):
        body = summarize(api_client, factories.device())

        narrative = body["data"]["narrative"]
        assert narrative["available"] is False
        assert "No AI credentials configured" in narrative["reason"]
        assert "NVIDIA_API_KEY" in narrative["reason"]
        assert "produced deterministically" in narrative["reason"]

    def test_findings_are_unaffected_by_the_absence_of_ai(self, api_client):
        body = summarize(api_client, factories.device(drift_seconds=7200.0))

        assert body["success"] is True
        assert body["data"]["counts"]["CRITICAL"] >= 1

    def test_narration_can_be_declined(self, api_client):
        body = summarize(api_client, factories.device(), narrate=False)

        assert "narrative" not in body["data"]

    def test_a_failing_llm_call_does_not_fail_the_analysis(self, api_client, monkeypatch):
        """Narration is an enhancement; its failure must degrade, not raise."""
        monkeypatch.setattr(agent, "AI_ENABLED", True)
        monkeypatch.setattr(agent, "NVIDIA_API_KEY", "test-key")

        def explode(*args, **kwargs):
            raise RuntimeError("connection refused")


        monkeypatch.setattr(agent.requests, "post", explode)

        body = summarize(api_client, factories.device())

        assert body["success"] is True
        assert body["data"]["narrative"]["available"] is False
        assert "connection refused" in body["data"]["narrative"]["reason"]

    def test_a_successful_llm_call_is_attributed_to_its_model(self, api_client, monkeypatch):
        monkeypatch.setattr(agent, "AI_ENABLED", True)
        monkeypatch.setattr(agent, "NVIDIA_API_KEY", "test-key")

        class _Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": "Two findings of note."}}],
                    "usage": {"total_tokens": 42},
                }

        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["prompt"] = json["messages"][0]["content"]
            return _Response()

        monkeypatch.setattr(agent.requests, "post", fake_post)

        body = summarize(api_client, factories.device(drift_seconds=7200.0))

        assert body["data"]["narrative"] == {
            "available": True,
            "provider": "NVIDIA NIM",
            "model": agent.NVIDIA_MODEL,
            "summary": "Two findings of note.",
            "usage": {"total_tokens": 42},
        }
        assert captured["url"].endswith("/chat/completions")
        # The prompt must not invite the model to assert tampering.
        assert "Do not invent facts" in captured["prompt"]
        assert "Do not assert that evidence was tampered" in captured["prompt"]


class TestAnalysisHealth:
    def test_health_reports_that_findings_work_without_ai(self, api_client, monkeypatch):
        monkeypatch.setattr(agent, "AI_ENABLED", False)

        body = api_client.get("/api/analysis/health").json()

        assert body["success"] is True
        assert body["data"]["deterministic_findings"] is True
        assert body["data"]["ai_narration_configured"] is False
        assert body["data"]["model"] is None


def test_analysis_of_a_real_probe_result(api_client, hik_client, hikvision_server):
    """The endpoint accepts exactly what the probe pipeline produces."""
    from vendors.hikvision import HikvisionAdapter

    hikvision_server.clock_offset_seconds = 4000.0
    adapter = HikvisionAdapter()
    device = adapter.identify(hik_client)
    index = adapter.search_recordings(
        hik_client,
        ["1"],
        datetime(2026, 9, 4, tzinfo=timezone.utc),
        datetime(2026, 9, 5, tzinfo=timezone.utc),
    )

    body = summarize(api_client, device, index)

    assert body["success"] is True
    assert any(f["severity"] == "CRITICAL" for f in body["data"]["findings"])
    assert "Channel 1 has 1 gap(s) in its recording index" in titles(body)
    assert body["data"]["device"]["serial_number"].startswith("DS-7208HQHI-K1")
