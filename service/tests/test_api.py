"""HTTP surface: the envelopes the VigiTrace server actually consumes.

The server is this service's only client, so the response envelope is a
contract. These tests exercise it end to end against the mock recorders rather
than mocking the service layer, because the envelope is only useful if it
survives a real probe.
"""

import hashlib

from tests.conftest import make_target
from tests.mock_dvr import hikvision as hik_mock

DETECT = "/api/devices/detect"
IDENTIFY = "/api/devices/identify"
ENUMERATE = "/api/devices/enumerate"
SEARCH = "/api/recordings/search"
TIMELINE = "/api/recordings/timeline"
ACQUIRE = "/api/recordings/acquire"
VERIFY = "/api/integrity/verify"

WINDOW = {"start": "2026-09-04T00:00:00Z", "end": "2026-09-05T00:00:00Z"}


def target_payload(server, **kwargs):
    return make_target(server, **kwargs).model_dump(mode="json")


class TestServiceHealth:
    def test_root_describes_the_service(self, api_client):
        body = api_client.get("/").json()

        assert body["success"] is True
        assert "/docs" in body["message"]

    def test_health_reports_success(self, api_client):
        response = api_client.get("/health")

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_an_unknown_route_is_a_plain_404(self, api_client):
        assert api_client.get("/api/nonexistent").status_code == 404


class TestVendorRegistry:
    def test_every_registered_adapter_is_described(self, api_client):
        body = api_client.get("/api/devices/vendors").json()

        vendors = body["data"]["vendors"]
        assert body["success"] is True
        assert {v["vendor"] for v in vendors} == {"HIKVISION", "DAHUA", "CPPLUS", "GODREJ"}
        assert body["message"] == f"{len(vendors)} vendor adapter(s) registered."

    def test_each_adapter_states_its_evidential_basis(self, api_client):
        vendors = {
            v["vendor"]: v for v in api_client.get("/api/devices/vendors").json()["data"]["vendors"]
        }

        assert "ISAPI" in vendors["HIKVISION"]["provenance"]
        assert "NetSDK excluded" in vendors["DAHUA"]["provenance"]
        assert "Dahua firmware" in vendors["CPPLUS"]["provenance"]
        assert "XiongMai" in vendors["GODREJ"]["provenance"]

    def test_families_and_private_ports_are_reported(self, api_client):
        vendors = {
            v["vendor"]: v for v in api_client.get("/api/devices/vendors").json()["data"]["vendors"]
        }

        assert vendors["CPPLUS"]["family"] == "DAHUA"
        assert vendors["GODREJ"]["family"] == "XIONGMAI"
        assert vendors["HIKVISION"]["sdk_port"] == 8000
        assert vendors["DAHUA"]["sdk_port"] == 37777
        assert vendors["GODREJ"]["sdk_port"] == 34567

    def test_capabilities_are_reported_per_adapter(self, api_client):
        vendors = {
            v["vendor"]: v for v in api_client.get("/api/devices/vendors").json()["data"]["vendors"]
        }

        assert "SEARCH_RECORDINGS" in vendors["HIKVISION"]["capabilities"]
        # The XiongMai adapter cannot search recordings and does not claim to.
        assert "SEARCH_RECORDINGS" not in vendors["GODREJ"]["capabilities"]


class TestDetectEndpoint:
    def test_a_recognised_recorder_is_reported_with_its_signals(
        self, api_client, hikvision_server
    ):
        body = api_client.post(DETECT, json=target_payload(hikvision_server)).json()

        assert body["success"] is True
        assert body["detection"]["vendor"] == "HIKVISION"
        assert body["detection"]["confidence"] == "CONFIRMED"
        assert body["detection"]["signals"]
        assert body["device"] is None

    def test_an_unrecognised_host_is_an_unsupported_vendor(self, api_client, blank_server):
        response = api_client.post(DETECT, json=target_payload(blank_server))
        body = response.json()

        assert response.status_code == 200
        assert body["success"] is False
        assert body["error"]["code"] == "UNSUPPORTED_VENDOR"
        assert body["detection"]["vendor"] == "UNKNOWN"
        assert body["error"]["remediation"]


class TestIdentifyEndpoint:
    def test_retained_artifacts_name_the_cgi_action_they_came_from(
        self, api_client, dahua_server
    ):
        """Provenance is per call, and on Dahua the call is the action."""
        body = api_client.post(IDENTIFY, json=target_payload(dahua_server)).json()

        artifacts = body["device"]["evidence"]["artifacts"]
        endpoints = [a["endpoint"] for a in artifacts]

        assert "/cgi-bin/magicBox.cgi?action=getSystemInfo" in endpoints
        assert "/cgi-bin/magicBox.cgi?action=getMachineName" in endpoints
        # One label may repeat when the same action is called twice, but two
        # different payloads must never end up under the same label.
        by_endpoint: dict[str, set[str]] = {}
        for artifact in artifacts:
            by_endpoint.setdefault(artifact["endpoint"], set()).add(artifact["sha256"])
        assert all(len(digests) == 1 for digests in by_endpoint.values())

    def test_a_full_device_object_is_returned(self, api_client, hikvision_server):
        body = api_client.post(IDENTIFY, json=target_payload(hikvision_server)).json()

        assert body["success"] is True
        device = body["device"]
        assert device["identity"]["serial_number"] == hik_mock.SERIAL_NUMBER
        assert len(device["channels"]) == 6
        assert device["storage"][0]["capacity_bytes"] == 2000398843904
        assert device["clock"]["drift_seconds"] is not None
        assert device["raw"]["/ISAPI/System/deviceInfo"]["model"] == hik_mock.MODEL
        assert device["evidence"]["artifacts"]

    def test_identification_requires_credentials(self, api_client, hikvision_server):
        payload = target_payload(hikvision_server)
        payload["credentials"] = None

        body = api_client.post(IDENTIFY, json=payload).json()

        assert body["success"] is False
        # Detection itself fails first on a password-protected recorder, so the
        # code is AUTH_FAILED either way.
        assert body["error"]["code"] == "AUTH_FAILED"

    def test_a_moved_private_protocol_port_is_honoured(
        self, api_client, blank_server, dvrip_server
    ):
        """sdk_port is how an operator reaches a recorder that is not on 34567."""
        payload = target_payload(blank_server)
        payload["sdk_port"] = dvrip_server.port

        body = api_client.post(IDENTIFY, json=payload).json()

        assert body["success"] is True
        assert body["device"]["identity"]["vendor"] == "GODREJ"
        assert body["device"]["network"]["sdk_port"] == dvrip_server.port
        # Attribution for this family is fingerprint-derived, never confirmed.
        assert body["detection"]["confidence"] == "PROBABLE"

    def test_enumerate_refreshes_the_same_standardized_object(
        self, api_client, hikvision_server
    ):
        body = api_client.post(ENUMERATE, json=target_payload(hikvision_server)).json()

        assert body["success"] is True
        assert len(body["device"]["channels"]) == 6
        assert body["device"]["storage"][0]["status"] == "ok"


class TestRecordingEndpoints:
    def test_search_returns_the_recorder_index(self, api_client, hikvision_server):
        body = api_client.post(
            SEARCH,
            json={"target": target_payload(hikvision_server), "channel_ids": ["1"], **WINDOW},
        ).json()

        assert body["success"] is True
        assert len(body["index"]["recordings"]) == 3
        assert body["message"] == "Found 3 recording segment(s)."

    def test_an_empty_window_is_rejected_before_the_device_is_touched(
        self, api_client, hikvision_server
    ):
        body = api_client.post(
            SEARCH,
            json={
                "target": target_payload(hikvision_server),
                "channel_ids": ["1"],
                "start": "2026-09-05T00:00:00Z",
                "end": "2026-09-04T00:00:00Z",
            },
        ).json()

        assert body["success"] is False
        assert body["error"]["code"] == "PROTOCOL_ERROR"
        assert hikvision_server.requests == []

    def test_timeline_normalizes_the_index_against_the_measured_drift(
        self, api_client, hikvision_server
    ):
        hikvision_server.clock_offset_seconds = 300.0

        body = api_client.post(
            TIMELINE,
            json={"target": target_payload(hikvision_server), "channel_ids": ["1"], **WINDOW},
        ).json()

        assert body["success"] is True
        timeline = body["data"]["timeline"]
        assert timeline["segment_count"] == 3
        assert timeline["gap_count"] == 1
        assert 280 < timeline["drift_seconds_applied"] < 320
        assert body["data"]["coverage"]["1"]["segments"] == 3

    def test_timeline_refuses_to_guess_when_the_device_cannot_be_identified(
        self, api_client, blank_server
    ):
        body = api_client.post(
            TIMELINE,
            json={"target": target_payload(blank_server), "channel_ids": ["1"], **WINDOW},
        ).json()

        assert body["success"] is False
        assert "clock offset is unknown" in body["message"]

    def test_acquire_stores_the_segment_and_reports_its_hashes(
        self, api_client, hikvision_server, evidence_dir
    ):
        body = api_client.post(
            ACQUIRE,
            json={
                "target": target_payload(hikvision_server),
                "recording_id": "rec-1",
                "channel_id": "1",
                "start": "2026-09-04T08:00:00Z",
                "end": "2026-09-04T09:00:00Z",
                "playback_uri": hikvision_server.playback_uri(0),
            },
        ).json()

        assert body["success"] is True
        acquisition = body["acquisition"]
        assert acquisition["size_bytes"] == len(hik_mock.DOWNLOAD_PAYLOAD)
        assert acquisition["sha256"] == hashlib.sha256(hik_mock.DOWNLOAD_PAYLOAD).hexdigest()
        assert acquisition["warnings"]  # the advertised size does not match


class TestIntegrityEndpoint:
    def test_an_untouched_artifact_verifies(self, api_client, tmp_path):
        path = tmp_path / "a.bin"
        path.write_bytes(b"evidence")

        body = api_client.post(
            VERIFY,
            json={
                "artifacts": [
                    {
                        "recording_id": "rec-1",
                        "stored_path": str(path),
                        "expected_sha256": hashlib.sha256(b"evidence").hexdigest(),
                    }
                ]
            },
        ).json()

        assert body["success"] is True
        assert body["data"]["verified"] == 1
        assert body["data"]["failed"] == 0
        assert body["data"]["results"][0]["recording_id"] == "rec-1"

    def test_one_bad_artifact_does_not_hide_the_others(self, api_client, tmp_path):
        good = tmp_path / "good.bin"
        good.write_bytes(b"evidence")
        bad = tmp_path / "bad.bin"
        bad.write_bytes(b"altered")

        body = api_client.post(
            VERIFY,
            json={
                "artifacts": [
                    {
                        "recording_id": "rec-1",
                        "stored_path": str(good),
                        "expected_sha256": hashlib.sha256(b"evidence").hexdigest(),
                    },
                    {
                        "recording_id": "rec-2",
                        "stored_path": str(bad),
                        "expected_sha256": hashlib.sha256(b"evidence").hexdigest(),
                    },
                    {
                        "recording_id": "rec-3",
                        "stored_path": str(tmp_path / "absent.bin"),
                        "expected_sha256": "0" * 64,
                    },
                ]
            },
        ).json()

        assert body["success"] is False
        assert body["data"]["verified"] == 1
        assert body["data"]["failed"] == 2
        results = {r["recording_id"]: r for r in body["data"]["results"]}
        assert results["rec-1"]["verified"] is True
        assert "does not match" in results["rec-2"]["reason"]
        assert "missing from storage" in results["rec-3"]["reason"]

    def test_an_acquisition_verifies_against_its_own_recorded_digest(
        self, api_client, hikvision_server, evidence_dir
    ):
        acquired = api_client.post(
            ACQUIRE,
            json={
                "target": target_payload(hikvision_server),
                "recording_id": "rec-1",
                "channel_id": "1",
                "start": "2026-09-04T08:00:00Z",
                "end": "2026-09-04T09:00:00Z",
                "playback_uri": hikvision_server.playback_uri(0),
            },
        ).json()["acquisition"]

        body = api_client.post(
            VERIFY,
            json={
                "artifacts": [
                    {
                        "recording_id": acquired["recording_id"],
                        "stored_path": acquired["stored_path"],
                        "expected_sha256": acquired["sha256"],
                    }
                ]
            },
        ).json()

        assert body["success"] is True
        assert body["data"]["results"][0]["size_bytes"] == acquired["size_bytes"]


class TestErrorEnvelopes:
    def test_a_malformed_request_is_rejected_by_validation(self, api_client):
        response = api_client.post(DETECT, json={"http_port": 80})

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "host"]

    def test_unknown_fields_are_refused_rather_than_ignored(self, api_client):
        """Vendor or client drift must surface loudly, not be swallowed."""
        response = api_client.post(DETECT, json={"host": "192.0.2.1", "unexpected": True})

        assert response.status_code == 422

    def test_the_service_exception_handler_produces_the_house_envelope(self):
        import sys

        from app import handle_vigitrace_exception
        from utils.exception import VigiTraceException

        exception = VigiTraceException("Recorder went away.", sys, status_code=502)
        response = handle_vigitrace_exception(None, exception)

        assert response.status_code == 502
        assert b'"success":false' in response.body
        assert b"Recorder went away." in response.body
