import unittest
from guzzionboard_core import DiagnosticCode, Mode, SafetyGate, SimulatorTransport


class CoreTests(unittest.TestCase):
    def test_simulator_is_disconnected_until_explicit_connect(self):
        ecu = SimulatorTransport()
        self.assertFalse(ecu.connected)
        ecu.connect()
        self.assertTrue(ecu.connected)
        self.assertGreater(ecu.values().rpm, 0)

    def test_live_values_have_stable_api_shape(self):
        values = SimulatorTransport().values().json_values()
        self.assertEqual(set(values), {"timestamp", "rpm", "coolant", "battery", "throttle", "air", "lambda"})

    def test_clear_faults_is_local_to_simulator(self):
        ecu = SimulatorTransport()
        self.assertEqual(len(ecu.faults), 2)
        ecu.clear_faults()
        self.assertEqual(ecu.faults, [])

    def test_writes_are_never_allowed_in_simulator(self):
        gate = SafetyGate(Mode.SIMULATOR)
        self.assertFalse(gate.allow_write(identified=True, stable_power=True,
                                          verified_backup=True, compatible_image=True,
                                          explicit_confirmation=True))

    def test_read_only_requires_every_safety_check(self):
        gate = SafetyGate(Mode.READ_ONLY)
        self.assertFalse(gate.allow_write(identified=True, stable_power=True,
                                          verified_backup=True, compatible_image=True))
        self.assertTrue(gate.allow_write(identified=True, stable_power=True,
                                         verified_backup=True, compatible_image=True,
                                         explicit_confirmation=True))


if __name__ == "__main__":
    unittest.main()
