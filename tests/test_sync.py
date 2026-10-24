import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

import sync


class DownloadOutputTests(unittest.TestCase):
    def run_download(self, output, returncode=0, clock=None):
        self.notifier = Mock()
        proc = Mock()
        proc.stdout = io.TextIOWrapper(io.BytesIO(output.encode()), encoding="utf-8")
        proc.poll.return_value = returncode
        proc.wait.return_value = returncode
        with patch.dict(sync.os.environ, {}, clear=True), \
                patch.object(sync.subprocess, "Popen", return_value=proc), \
                patch.object(sync, "log") as logger, \
                patch.object(sync.time, "monotonic", side_effect=clock), \
                patch.object(sync, "running", True):
            result = sync.run_megatools_download(
                "https://mega.nz/folder/EXAMPLE#EXAMPLE", "/downloads",
                notifier=self.notifier,
            )
            self.messages = [call.args[0] for call in logger.call_args_list]
            self.command = sync.subprocess.Popen.call_args.args[0]
            return result

    def test_invalid_link_is_not_an_existing_file(self):
        self.assertEqual(self.run_download(
            "WARNING: Skipping invalid Mega download link: EXAMPLE\n"
        ), (False, 0, 0))

    def test_undecryptable_node_fails_even_with_zero_exit_status(self):
        self.assertEqual(self.run_download(
            "WARNING: Skipping FS node EXAMPLE because key can't be decrypted\n"
        ), (False, 0, 0))

    def test_critical_assertion_is_a_failure(self):
        self.assertEqual(self.run_download(
            "CRITICAL: b64_aes128_decrypt: assertion 'key != NULL' failed\n"
        ), (False, 0, 0))

    def test_quota_is_not_success(self):
        self.assertEqual(self.run_download(
            "Transfer quota exceeded\n"
        ), (False, 0, 0))

    def test_quota_509_detected_as_limit(self):
        self.assertEqual(self.run_download(
            "WARNING: chunk download failed (Server returned 509 (over quota)), re-trying after 256 seconds\n"
        ), (False, 0, 0))
        self.assertTrue(any("[Limit]" in line for line in self.messages))
        self.assertFalse(any("[Fehler]" in line for line in self.messages))

    def test_known_success_messages(self):
        self.assertEqual(self.run_download(
            "already downloaded: existing.txt\nDownloaded: new.txt\n"
        ), (True, 1, 1))

    def test_nonzero_exit_is_a_failure(self):
        self.assertEqual(self.run_download("", 1), (False, 0, 0))

    def test_unknown_skip_is_not_counted_as_existing(self):
        self.assertEqual(self.run_download(
            "Skipping FS node EXAMPLE\n"
        ), (False, 0, 0))

    def test_existing_file_is_not_an_error(self):
        self.assertEqual(self.run_download(
            "ERROR: File already exists at /downloads/existing.txt\n"
        ), (True, 0, 1))
        self.assertTrue(any("[Vorhanden, übersprungen]" in line for line in self.messages))
        self.assertFalse(any("[Fehler]" in line for line in self.messages))

    def test_exit_one_with_existing_files_is_not_a_download_failure(self):
        self.assertEqual(self.run_download(
            "ERROR: File already exists at /downloads/one.txt\n"
            "ERROR: File already exists at /downloads/two.txt\n", 1
        ), (True, 0, 2))
        self.assertTrue(any("Statuscode 1" in line and "vorhandener Dateien" in line
                            for line in self.messages))

    def test_exit_one_with_downloads_and_existing_files(self):
        self.assertEqual(self.run_download(
            "Downloaded: new.txt\n"
            "ERROR: File already exists at /downloads/existing.txt\n", 1
        ), (True, 1, 1))

    def test_other_exit_codes_with_existing_files_remain_failures(self):
        for code in (2, -15):
            with self.subTest(code=code):
                self.assertEqual(self.run_download(
                    "ERROR: File already exists at /downloads/existing.txt\n", code
                ), (False, 0, 1))

    def test_exit_one_without_known_existing_file_error_remains_failure(self):
        self.assertEqual(self.run_download(
            "already downloaded: existing.txt\n", 1
        ), (False, 0, 1))

    def test_existing_files_do_not_hide_other_failures_with_exit_one(self):
        for error in (
            "WARNING: Skipping FS node EXAMPLE because key can't be decrypted",
            "CRITICAL: b64_aes128_decrypt: assertion 'key != NULL' failed",
            "Transfer quota exceeded",
            "ERROR: Can't create local directory /downloads/example: file exists",
            "ERROR: Download failed for new.txt: Network error",
            "Skipping FS node EXAMPLE",
        ):
            with self.subTest(error=error):
                self.assertEqual(self.run_download(
                    "ERROR: File already exists at /downloads/existing.txt\n"
                    + error + "\n", 1
                ), (False, 0, 1))

    def test_existing_directory_conflict_stays_an_error(self):
        self.assertEqual(self.run_download(
            "ERROR: Can't create local directory /downloads/example: file exists\n"
        ), (False, 0, 0))

    def test_progress_handles_carriage_returns_ansi_and_throttling(self):
        self.run_download(
            "\x1b[32mone.bin\x1b[0m: 1% - 1 MiB of 100 MiB\r"
            "one.bin: 2% - 2 MiB of 100 MiB\r"
            "one.bin: 20% - 20 MiB of 100 MiB\r"
            "one.bin: 100% - 100 MiB of 100 MiB\r"
            "two.bin: 0% - 0 MiB of 100 MiB\r",
            clock=[100, 101, 110, 111, 112],
        )
        progress = [line for line in self.messages if line.startswith("[Fortschritt]")]
        self.assertEqual(len(progress), 4)
        self.assertIn("1%", progress[0])
        self.assertIn("20%", progress[1])
        self.assertIn("100%", progress[2])
        self.assertIn("two.bin", progress[3])
        self.assertFalse(any("\x1b" in line for line in self.messages))
        self.assertNotIn("--no-progress", self.command)

    def test_existing_file_does_not_hide_decryption_error(self):
        self.assertEqual(self.run_download(
            "ERROR: File already exists at /downloads/existing.txt\n"
            "WARNING: Skipping FS node EXAMPLE because key can't be decrypted\n"
        ), (False, 0, 1))

    def test_telegram_progress_new_files_and_completion(self):
        self.assertEqual(self.run_download(
            "one.bin: 1% - 1 MiB\r"
            "one.bin: 2% - 2 MiB\r"
            "one.bin: 50% - 50 MiB\r"
            "one.bin: 100% - 100 MiB\r"
            "one.bin: 100% - 100 MiB\r"
            "Downloaded: one.bin\n"
            "two.bin: 0% - 0 MiB\r",
            clock=[100, 110, 160, 161, 162, 163],
        ), (True, 1, 0))
        messages = [call.args[0] for call in self.notifier.send.call_args_list]
        self.assertEqual(sum("Neue oder unvollständige" in msg for msg in messages), 2)
        progress = [msg for msg in messages if "Download-Fortschritt" in msg]
        self.assertEqual(len(progress), 4)
        self.assertIn("1%", progress[0])
        self.assertIn("50%", progress[1])
        self.assertIn("100%", progress[2])
        self.assertIn("two.bin", progress[3])
        self.assertTrue(any("Download abgeschlossen" in msg for msg in messages))
        self.assertFalse(any("https://mega.nz" in msg for msg in messages))

    def test_existing_files_do_not_trigger_new_download_alerts(self):
        self.run_download(
            "ERROR: File already exists at /downloads/existing.txt\n"
            "already downloaded: existing.txt\n"
        )
        self.notifier.send.assert_not_called()

    def test_quota_alert_is_sent_only_once_per_link(self):
        self.run_download("Transfer quota exceeded\nTransfer quota exceeded\n")
        self.notifier.send.assert_called_once()
        self.assertIn("Transferlimit", self.notifier.send.call_args.args[0])


class TelegramNotifierTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(sync.os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:test-secret",
            "TELEGRAM_CHAT_ID": "-12345",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.notifier = sync.TelegramNotifier()

    def test_sends_plain_text_json_with_timeout(self):
        with patch.object(sync, "urlopen") as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(b'{"ok": true}')
            self.notifier.send("Datei <test> & *Name*")
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.telegram.org/bot123:test-secret/sendMessage")
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {
            "chat_id": "-12345", "text": "Datei <test> & *Name*",
        })
        self.assertEqual(opener.call_args.kwargs["timeout"], 10)

    def test_unconfigured_notifier_does_not_use_network(self):
        with patch.dict(sync.os.environ, {}, clear=True), \
                patch.object(sync, "urlopen") as opener:
            sync.TelegramNotifier().send("Test")
        opener.assert_not_called()

    def test_partial_configuration_warns_and_does_not_send(self):
        for missing in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            with self.subTest(missing=missing), \
                    patch.dict(sync.os.environ, {missing: ""}), \
                    patch.object(sync, "log") as logger, \
                    patch.object(sync, "urlopen") as opener:
                sync.TelegramNotifier().send("Test")
                logger.assert_called_once()
                self.assertEqual(logger.call_args.args[1], "WARN")
                opener.assert_not_called()

    def test_send_failures_are_logged_without_secrets(self):
        failures = [
            HTTPError("https://example/123:test-secret", 429, "123:test-secret", {}, None),
            URLError("https://example/123:test-secret"),
            TimeoutError("123:test-secret"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(sync, "urlopen", side_effect=failure), \
                    patch.object(sync, "log") as logger:
                self.notifier.send("Test")
                logger.assert_called_once()
                self.assertNotIn("123:test-secret", logger.call_args.args[0])

    def test_invalid_and_unsuccessful_api_responses_warn(self):
        for body in (b'{"ok": false}', b'invalid JSON', b'[]'):
            with self.subTest(body=body), \
                    patch.object(sync, "urlopen") as opener, \
                    patch.object(sync, "log") as logger:
                opener.return_value.__enter__.return_value = io.BytesIO(body)
                self.notifier.send("Test")
                logger.assert_called_once()

    def test_long_unicode_messages_stay_under_telegram_limit(self):
        with patch.object(sync, "urlopen") as opener:
            opener.return_value.__enter__.return_value = io.BytesIO(b'{"ok": true}')
            self.notifier.send("\U0001f600" * 5000)
        text = json.loads(opener.call_args.args[0].data)["text"]
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)
        self.assertTrue(text.endswith("..."))

    def test_telegram_outage_does_not_fail_successful_download(self):
        proc = Mock()
        proc.stdout = io.StringIO("Downloaded: new.txt\n")
        proc.poll.return_value = 0
        proc.wait.return_value = 0
        with patch.object(sync.subprocess, "Popen", return_value=proc), \
                patch.object(sync, "urlopen", side_effect=URLError("offline")), \
                patch.object(sync, "running", True), \
                patch.object(sync, "log") as logger:
            result = sync.run_megatools_download(
                "https://mega.nz/folder/EXAMPLE#EXAMPLE", "/downloads",
                notifier=self.notifier,
            )
        self.assertEqual(result, (True, 1, 0))
        self.assertTrue(any("Telegram-Nachricht fehlgeschlagen" in call.args[0]
                            for call in logger.call_args_list))


class ScanNotificationTests(unittest.TestCase):
    def run_scan(self, results, active=True):
        with tempfile.TemporaryDirectory() as download_dir, \
                patch.object(sync, "read_links", return_value=[
                    {"url": f"https://mega.nz/folder/{idx}#SECRET", "target_subdir": None}
                    for idx in range(len(results))
                ]), \
                patch.object(sync, "TelegramNotifier") as notifier_class, \
                patch.object(sync, "run_megatools_download", side_effect=results) as download, \
                patch.object(sync, "log"), \
                patch.object(sync, "running", active):
            count = sync.process_links("unused.txt", download_dir)
        self.download = download
        self.notifier = notifier_class.return_value
        self.messages = [call.args[0] for call in self.notifier.send.call_args_list]
        return count

    def test_scan_totals_and_errors_without_private_links(self):
        self.assertEqual(self.run_scan([(True, 2, 3), (False, 1, 4)]), 2)
        self.assertIn("gestartet (2 Links)", self.messages[0])
        self.assertIn("Link 2/2 fehlgeschlagen", self.messages[1])
        self.assertIn("3 Download-Abschlüsse", self.messages[-1])
        self.assertIn("7 vorhanden/übersprungen", self.messages[-1])
        self.assertIn("1 Links fehlgeschlagen", self.messages[-1])
        self.assertFalse(any("SECRET" in msg for msg in self.messages))
        for call in self.download.call_args_list:
            self.assertIs(call.kwargs["notifier"], self.notifier)

    def test_scan_with_no_new_downloads_still_reports_result(self):
        self.run_scan([(True, 0, 5)])
        self.assertIn("0 Download-Abschlüsse", self.messages[-1])
        self.assertIn("0 Links fehlgeschlagen", self.messages[-1])

    def test_existing_file_exit_one_does_not_send_telegram_failure(self):
        proc = Mock()
        proc.stdout = io.StringIO(
            "ERROR: File already exists at /downloads/existing.txt\n"
        )
        proc.poll.return_value = 1
        proc.wait.return_value = 1
        with tempfile.TemporaryDirectory() as download_dir, \
                patch.dict(sync.os.environ, {}, clear=True), \
                patch.object(sync, "read_links", return_value=[
                    {"url": "https://mega.nz/folder/EXAMPLE#SECRET", "target_subdir": None}
                ]), \
                patch.object(sync.subprocess, "Popen", return_value=proc), \
                patch.object(sync, "TelegramNotifier") as notifier_class, \
                patch.object(sync, "log"), \
                patch.object(sync, "running", True):
            self.assertEqual(sync.process_links("unused.txt", download_dir), 1)
        messages = [call.args[0] for call in notifier_class.return_value.send.call_args_list]
        self.assertEqual(len(messages), 2)
        self.assertIn("1 vorhanden/übersprungen", messages[-1])
        self.assertIn("0 Links fehlgeschlagen", messages[-1])
        self.assertFalse(any("Link 1/1 fehlgeschlagen" in msg for msg in messages))

    def test_empty_configuration_does_not_send_messages(self):
        self.assertEqual(self.run_scan([]), 0)
        self.assertEqual(self.messages, [])

    def test_interrupted_scan_is_not_reported_as_completed(self):
        self.run_scan([(True, 0, 0)], active=False)
        self.download.assert_not_called()
        self.assertIn("abgebrochen", self.messages[-1])


class DeploymentTests(unittest.TestCase):
    def test_logo_paths_resolve_to_tracked_asset(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('src="Icon.png"', (root / "README.md").read_text())
        self.assertEqual((root / "Icon.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        template = ET.parse(root / "megasync-unraid-template.xml").getroot()
        self.assertEqual(template.findtext("Icon"),
                         "https://raw.githubusercontent.com/SwissLuckyFox/Megasync/main/Icon.png")
        config = {item.attrib["Target"]: item for item in template.findall("Config")}
        self.assertEqual(config["TELEGRAM_BOT_TOKEN"].attrib["Mask"], "true")
        self.assertIn("TELEGRAM_CHAT_ID", config)


if __name__ == "__main__":
    unittest.main()
