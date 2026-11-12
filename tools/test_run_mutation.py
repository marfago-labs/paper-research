"""Offline tests for run_mutation.py. Run: python tools/test_run_mutation.py"""

import contextlib
import socket
import unittest
from unittest import mock

import run_mutation

CONFIG = '[cosmic-ray]\nmodule-path = "x.py"\n\n[cosmic-ray.distributor]\nname = "local"\n'


class Ports(unittest.TestCase):
    def test_every_worker_gets_its_own_free_port(self):
        ports = run_mutation.free_ports(4)
        self.assertEqual(len(set(ports)), 4)
        for port in ports:
            with contextlib.closing(socket.socket()) as probe:
                probe.bind(("127.0.0.1", port))  # still free, so a worker can take it


class Startup(unittest.TestCase):
    def test_a_worker_that_has_stopped_is_reported_whatever_listens_on_its_port(self):
        with contextlib.closing(socket.socket()) as other:
            other.bind(("127.0.0.1", 0))
            other.listen()
            stopped = mock.Mock()
            stopped.poll.return_value = 1
            with self.assertRaisesRegex(SystemExit, "stopped before it was ready"):
                run_mutation.wait_until_listening(other.getsockname()[1], stopped)

    def test_a_running_worker_is_ready_once_its_port_listens(self):
        with contextlib.closing(socket.socket()) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            running = mock.Mock()
            running.poll.return_value = None
            run_mutation.wait_until_listening(listener.getsockname()[1], running)

    def test_a_worker_that_never_listens_is_reported(self):
        running = mock.Mock()
        running.poll.return_value = None
        with mock.patch.object(run_mutation, "STARTUP", 0), self.assertRaisesRegex(SystemExit, "did not start"):
            run_mutation.wait_until_listening(run_mutation.free_ports(1)[0], running)


class Configuration(unittest.TestCase):
    def test_mutants_are_sent_to_the_workers(self):
        text = run_mutation.http_config(CONFIG, [9001, 9002])
        self.assertIn('name = "http"', text)
        self.assertIn("worker-urls = ['http://127.0.0.1:9001', 'http://127.0.0.1:9002']", text)
        self.assertNotIn('name = "local"', text)
        self.assertIn('module-path = "x.py"', text)

    def test_windows_line_endings_are_read_too(self):
        self.assertIn('name = "http"', run_mutation.http_config(CONFIG.replace("\n", "\r\n"), [9001]))

    def test_a_configuration_without_the_local_distributor_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "expected the configuration to contain"):
            run_mutation.http_config('[cosmic-ray]\nmodule-path = "x.py"\n', [9001])


class Workers(unittest.TestCase):
    def test_one_worker_means_the_run_tests_mutants_itself(self):
        with run_mutation.workers(mock.Mock(), 1) as ports:
            self.assertEqual(ports, [])


if __name__ == "__main__":
    unittest.main()
