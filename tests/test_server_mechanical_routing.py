import unittest
from unittest.mock import patch

import server


class _Cad:
    app = object()


class _Backend:
    def __init__(self):
        self.backend = "pyzwcadmech"
        self.failover_calls = 0

    def snapshot(self):
        return {"active_backend": self.backend}

    def failover_from_pyzwcadmech(self, app, exc):
        self.failover_calls += 1
        self.backend = "zrx"
        return True


class MechanicalRunnerTests(unittest.TestCase):
    def test_read_operation_retries_after_switching_to_zrx(self):
        backend = _Backend()
        attempts = []

        def operation():
            attempts.append(None)
            if len(attempts) == 1:
                raise RuntimeError("ZwmToolKit type library failed")
            return {"data": "retried"}

        with patch.object(server, "_mechanical_backend", backend), patch.object(
            server, "get_cad_connection", return_value=(_Cad(), object())
        ), patch.object(server, "reset_cad_connection") as reset:
            result = server._run_mechanical("read", operation, read_only=True)

        self.assertEqual({"data": "retried"}, result)
        self.assertEqual(2, len(attempts))
        self.assertEqual(1, backend.failover_calls)
        reset.assert_called_once()

    def test_write_operation_switches_without_replaying(self):
        backend = _Backend()
        attempts = []

        def operation():
            attempts.append(None)
            raise RuntimeError("ZwmToolKit type library failed")

        with patch.object(server, "_mechanical_backend", backend), patch.object(
            server, "get_cad_connection", return_value=(_Cad(), object())
        ), patch.object(server, "reset_cad_connection"):
            result = server._run_mechanical("write", operation, read_only=False)

        self.assertEqual("MECHANICAL_BACKEND_SWITCHED_RETRY_REQUIRED", result["code"])
        self.assertEqual(1, len(attempts))
        self.assertEqual(1, backend.failover_calls)


if __name__ == "__main__":
    unittest.main()
