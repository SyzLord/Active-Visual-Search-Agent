import subprocess
import sys
from time import monotonic
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from search_agent.reader import OCR


class ReaderFailureTests(TestCase):
    def test_hung_worker_is_killed_and_close_is_idempotent(self):
        spawn = subprocess.Popen

        def stalled(*args, **kwargs):
            return spawn([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

        start = monotonic()
        with patch("search_agent.reader.subprocess.Popen", side_effect=stalled):
            worker = OCR(SimpleNamespace(node=sys.executable, env=None), timeout=.15)
        try:
            with self.assertRaisesRegex(RuntimeError, "超时"):
                worker.recognize(b"fake", (10, 10))
        finally:
            worker.close()
            worker.close()
        self.assertIsNotNone(worker.process.returncode)
        self.assertLess(monotonic() - start, 3)
