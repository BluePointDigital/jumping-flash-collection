import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from performance_probe import assess_virtual_input, require_virtual_input_acceptance


def sample(host_word, guest_word):
    return {
        'host': {'pad_word': host_word, 'input_focus': 0, 'release_gate_a_blocked': 1},
        'guest': {'slot0': {'buttons': guest_word, 'connected': True}},
    }


def report(samples):
    return {
        'neutral': {
            'host': {'controllers': 1, 'virtual_probe': 1, 'pad_word': 0xFFFF},
            'guest': {'slot0': {'buttons': '0xFFFF', 'connected': True}},
        },
        'samples': samples,
        'released': {
            'host': {'pad_word': 0xFFFF},
            'guest': {'slot0': {'buttons': '0xFFFF'}},
        },
    }


class VirtualInputAcceptanceTests(unittest.TestCase):
    def test_registered_but_neutral_probe_fails(self):
        result = assess_virtual_input(report([sample(0xFFFF, '0xFFFF')] * 4))
        self.assertTrue(result['device_registered'])
        self.assertFalse(result['guest_button_observed'])
        self.assertFalse(result['functional_check_passed'])
        self.assertIn('guest never reported the injected 0xBFFF button mask', result['failure_reasons'])
        with self.assertRaisesRegex(RuntimeError, 'Virtual SDL input functional check failed'):
            require_virtual_input_acceptance('jf1', result)

    def test_paired_press_and_release_pass(self):
        result = assess_virtual_input(report([
            sample(0xFFFF, '0xFFFF'),
            sample(0xBFFF, '0xBFFF'),
            sample(0xBFFF, '0xBFFF'),
            sample(0xFFFF, '0xFFFF'),
        ]))
        self.assertTrue(result['host_button_observed'])
        self.assertTrue(result['guest_button_observed'])
        self.assertTrue(result['paired_press_observed'])
        self.assertTrue(result['released'])
        self.assertTrue(result['functional_check_passed'])
        require_virtual_input_acceptance('jf1', result)

    def test_different_non_neutral_guest_mask_fails(self):
        result = assess_virtual_input(report([sample(0xBFFF, '0x7FFF')]))
        self.assertTrue(result['host_button_observed'])
        self.assertFalse(result['guest_button_observed'])
        self.assertFalse(result['paired_press_observed'])
        self.assertFalse(result['functional_check_passed'])
        self.assertIn('guest never reported the injected 0xBFFF button mask', result['failure_reasons'])


if __name__ == '__main__':
    unittest.main()
