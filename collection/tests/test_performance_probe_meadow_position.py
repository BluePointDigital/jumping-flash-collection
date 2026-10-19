"""Profile guards for the Robbit-only native Meadow position/action diagnostic."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from strict_input_probe import guard_robbit_meadow_profile, sample_robbit_meadow_position


class FakeClient:
    def __init__(self, profiles):
        self.profiles = list(profiles)
        self.status_calls = 0
        self.memory_reads = 0
        self.input_calls = 0

    def query(self, command, **kwargs):
        if command == "robbit_desktop_status":
            row = self.profiles[min(self.status_calls, len(self.profiles) - 1)]
            self.status_calls += 1
            return {"supported": 1, "modern": 1, "gameplay": 1,
                    "control_profile": row[0], "profile_changes": row[1]}
        if command == "mem_words":
            self.memory_reads += 1
            return {"words": ["0x1", "0x2", "0x3", "0x4", "0x5", "0x6"]}
        if command == "press":
            self.input_calls += 1
            return {"ok": True}
        raise AssertionError(f"unexpected query: {command}")


class MeadowPositionGuardTests(unittest.TestCase):
    def test_m15_rejected_before_position_read_or_input(self):
        client = FakeClient([("EVENT/07/M15.PEX", 9)])
        with self.assertRaisesRegex(RuntimeError, "only for EVENT/00/M01.PEX"):
            sample_robbit_meadow_position(client)
        self.assertEqual(client.memory_reads, 0)
        self.assertEqual(client.input_calls, 0)

    def test_stable_m01_sample_is_accepted(self):
        client = FakeClient([("EVENT/00/M01.PEX", 4), ("EVENT/00/M01.PEX", 4)])
        sample = sample_robbit_meadow_position(client)
        self.assertEqual(sample["profile_pin"], ("EVENT/00/M01.PEX", 4))
        self.assertEqual(sample["words"][:3], ["0x1", "0x2", "0x3"])
        self.assertEqual(client.memory_reads, 1)

    def test_profile_change_after_position_read_rejects_sample(self):
        client = FakeClient([("EVENT/00/M01.PEX", 4), ("EVENT/00/M01.PEX", 5)])
        with self.assertRaisesRegex(RuntimeError, "profile changed"):
            sample_robbit_meadow_position(client)
        self.assertEqual(client.memory_reads, 1)

    def test_profile_change_during_action_window_rejects_continuation(self):
        client = FakeClient([("EVENT/00/M01.PEX", 4), ("EVENT/00/M02.PEX", 5)])
        pin = guard_robbit_meadow_profile(client)
        client.query("press", buttons=0xFFEF, frames=1)
        with self.assertRaisesRegex(RuntimeError, "profile changed"):
            guard_robbit_meadow_profile(client, pin)
        self.assertEqual(client.input_calls, 1)


if __name__ == "__main__":
    unittest.main()
