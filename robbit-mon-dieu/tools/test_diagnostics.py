"""Timing receipts must reject gaps and invalid data, and compute percentiles correctly."""
import unittest
import io
from unittest.mock import patch, MagicMock
import diagnostics as d


class FakeClient:
    def __init__(self, rows):
        self.rows, self.frame = rows, 0
        self.commands = []

    def query(self, command, **args):
        self.commands.append((command,args))
        if command == 'frame_perf_samples':
            return dict(samples=[[1, 1, 16, 0]] if args['after'] == '0' else self.rows)
        if command == 'frame':
            self.frame += 60
            return dict(frame=self.frame)
        if command == 'audio_stats':
            return dict(out=dict(underruns=0))
        return {}


class ReceiptTests(unittest.TestCase):
    def collect(self, rows):
        with patch.object(d.time, 'sleep'), patch.object(d.time, 'monotonic', side_effect=[0,0,0,1,1]):
            return d.measure(FakeClient(rows), 1)

    def test_percentiles(self):
        result = self.collect([[2,2,10,0],[3,3,20,0],[4,4,110,0]])
        self.assertEqual(result['p99_ms'], 110)
        self.assertEqual(result['stalls_over_100_ms'], 1)
        self.assertEqual(result['guest_hz'], 60)

    def test_gap(self):
        with self.assertRaisesRegex(ValueError, '1 missing'):
            self.collect([[3,3,16,0]])

    def test_invalid_or_empty(self):
        for rows in ([], [[2,2,float('nan'),0]], [[2,2,0,0]]):
            with self.assertRaises(ValueError):
                self.collect(rows)

    def test_gameplay_releases_input_on_failure(self):
        client = FakeClient([[2,2,float('nan'),0]])
        with patch.object(d.time, 'sleep'), patch.object(d.time, 'monotonic', side_effect=[0,0,0]):
            with self.assertRaisesRegex(ValueError, 'Invalid timing'):
                d.measure(client, 1, exercise=True)
        self.assertIn(('press', dict(buttons=d.GAMEPLAY_ROUTE[0][0],frames=d.GAMEPLAY_ROUTE[0][1])),client.commands)
        self.assertEqual(client.commands[-1], ('clear_input',{}))

    def test_passive_never_changes_input(self):
        client = FakeClient([[2,2,16,0]])
        with patch.object(d.time, 'sleep'), patch.object(d.time, 'monotonic', side_effect=[0,0,0,1,1]):
            d.measure(client, 1)
        self.assertFalse(any(command in ('press','clear_input') for command,_ in client.commands))


class ClientTests(unittest.TestCase):
    def connection(self, response):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.makefile.return_value = io.BytesIO(response)
        return connection

    def test_fragmented_response_and_other_id(self):
        connection = self.connection(b'{"id":99,"ok":true}\n{\"id\":1,"ok":true,"edges":[\n{"frame":42}\n]}\n')
        with patch.object(d.socket, 'create_connection', return_value=connection):
            result = d.Client().query('load_transitions')
        self.assertEqual(result['edges'],[dict(frame=42)])
        self.assertEqual(connection.sendall.call_count,1)

    def test_incomplete_response_is_not_retried(self):
        connection = self.connection(b'{"id":1,"ok":true,\n')
        with patch.object(d.socket, 'create_connection', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                d.Client().query('savestate',op='save',slot=0)
        self.assertEqual(connection.sendall.call_count,1)


if __name__ == '__main__':
    unittest.main()
