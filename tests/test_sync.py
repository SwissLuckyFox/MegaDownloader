import io
import unittest
from unittest.mock import Mock, patch

import sync


class DownloadOutputTests(unittest.TestCase):
    def run_download(self, output, returncode=0):
        proc = Mock()
        proc.stdout = io.StringIO(output)
        proc.poll.return_value = returncode
        proc.wait.return_value = returncode
        with patch.dict(sync.os.environ, {}, clear=True), \
                patch.object(sync.subprocess, "Popen", return_value=proc), \
                patch.object(sync, "log"), \
                patch.object(sync, "running", True):
            return sync.run_megatools_download(
                "https://mega.nz/folder/EXAMPLE#EXAMPLE", "/downloads"
            )

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


if __name__ == "__main__":
    unittest.main()
