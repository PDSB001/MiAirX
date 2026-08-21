"""Unit tests for diagnostic bundle generation and log buffering."""

import json
import zipfile

from miairx.config.models import AppConfig
from miairx.core.log_buffer import LogBuffer, MemoryLogHandler
from miairx.web.diagnostics import build_diagnostics_bundle, redact_config


class TestRedactConfig:
    def test_masks_sensitive_fields(self):
        config = AppConfig(
            account="13800138000",
            password="secret-pass",
            cookie="userId=1; passToken=abc",
            web_password="admin123",
            mi_did="123",
            conf_path="/tmp/test",
        )
        data = redact_config(config)

        assert data["account"] == "138***"
        assert data["password"] == "***"
        assert data["cookie"] == "***"
        assert data["web_password"] == "***"

    def test_keeps_non_sensitive_fields(self):
        config = AppConfig(conf_path="/tmp/test", mi_did="123,456")
        data = redact_config(config)

        assert data["mi_did"] == "123,456"
        assert data["account"] == ""


class TestBuildBundle:
    def test_bundle_contains_expected_entries(self):
        class FakeApp:
            _is_running = True
            auth = None
            dlna_server = None
            ssdp = None
            _zeroconf = None
            _airplay_services = {}
            _speaker_health = {}
            config = AppConfig(conf_path="/tmp/test-nonexistent", mi_did="123")

        bundle = build_diagnostics_bundle(FakeApp())

        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
            assert "config.json" in names
            assert "system-info.json" in names
            system_info = json.loads(archive.read("system-info.json"))
            assert "ffmpeg" in system_info
            assert "xiaomi" in system_info
            assert "dlna" in system_info
            assert "airplay" in system_info

    def test_bundle_redacts_secrets_from_recent_logs(self, tmp_path):
        log_file = tmp_path / "miair.log"
        log_file.write_text(
            "password=secret-pass serviceToken=service-secret "
            "passToken=pass-secret cookie=userId=1\n"
            'payload={"serviceToken": "json-secret"}\n'
            "Authorization: Bearer bearer-secret\n",
            encoding="utf-8",
        )

        class FakeApp:
            _is_running = True
            auth = None
            dlna_server = None
            ssdp = None
            _zeroconf = None
            _airplay_services = {}
            _speaker_health = {}
            config = AppConfig(
                conf_path=str(tmp_path),
                password="secret-pass",
                cookie="userId=1; passToken=pass-secret",
                web_password="admin-secret",
            )

        bundle = build_diagnostics_bundle(FakeApp())

        with zipfile.ZipFile(bundle) as archive:
            sanitized_log = archive.read("miair.log")
        assert b"secret-pass" not in sanitized_log
        assert b"service-secret" not in sanitized_log
        assert b"pass-secret" not in sanitized_log
        assert b"json-secret" not in sanitized_log
        assert b"bearer-secret" not in sanitized_log


class TestLogBuffer:
    def test_appends_and_snapshots(self):
        buffer = LogBuffer(maxlen=3)
        buffer.append({"message": "a"})
        buffer.append({"message": "b"})
        buffer.append({"message": "c"})
        buffer.append({"message": "d"})

        messages = [r["message"] for r in buffer.snapshot()]
        assert messages == ["b", "c", "d"]

    def test_memory_handler_formats_record(self, caplog):
        import logging

        buffer = LogBuffer(maxlen=10)
        handler = MemoryLogHandler(buffer)
        logger = logging.getLogger("test_memory_handler")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            logger.info("hello buffer")
        finally:
            logger.removeHandler(handler)

        records = buffer.snapshot()
        assert any("hello buffer" in r["message"] for r in records)
