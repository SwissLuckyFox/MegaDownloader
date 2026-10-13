import io
import unittest
from unittest.mock import Mock, patch

import sync


class DownloadOutputTests(unittest.TestCase):
    def run_download(self, output, returncode=0, clock=None):
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
                "https://mega.nz/folder/EXAMPLE#EXAMPLE", "/downloads"
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


if __name__ == "__main__":
    unittest.main()
