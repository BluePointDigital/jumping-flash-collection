"""Focused acceptance failures for the process-local Robbit controller probe."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from strict_input_probe import run_probe


class FakeClient:
    def __init__(self, *, guest_button=None, camera_stalled=False):
        self.frame=100
        self.attached=False
        self.buttons=0
        self.axes=[0.0]*6
        self.guest_button=guest_button
        self.camera_stalled=camera_stalled
        self.camera_updates=10
        self.yaw=20
        self.pitch=-5
        self.profile_changes=3

    def query(self, command, **kwargs):
        if command=="frame":
            self.frame+=1
            return {"frame":self.frame}
        if command=="collection_input" and "enable" in kwargs:
            if kwargs["enable"]==0:
                self.attached=False
                self.buttons=0
                self.axes=[0.0]*6
            else:
                self.attached=True
                self.buttons=kwargs.get("buttons",0)
                self.axes=[kwargs.get("lx",0)/32767,kwargs.get("ly",0)/32767,
                           kwargs.get("rx",0)/32767,kwargs.get("ry",0)/32767,
                           kwargs.get("lt",0)/32767,kwargs.get("rt",0)/32767]
                if (abs(self.axes[2])+abs(self.axes[3])>.01) and not self.camera_stalled:
                    self.camera_updates+=4
                    self.yaw+=2
                    self.pitch-=1
            return self._host()
        if command=="collection_input":
            return self._host()
        if command=="pad_status":
            if self.attached and self.buttons&1:
                buttons=self.guest_button if self.guest_button is not None else 0xBFFF
            else:
                buttons=0xFFFF
            return {"slot0":{"buttons":f"0x{buttons:04X}"}}
        if command=="robbit_desktop_status":
            aiming=self.attached and (abs(self.axes[2])+abs(self.axes[3])>.01)
            return {"supported":1,"gameplay":1,"modern":1,"camera_updates":self.camera_updates,
                    "yaw":self.yaw,"pitch":self.pitch,"control_profile":"JM1/MAIN.PEX",
                    "profile_changes":self.profile_changes,"aim_owned":int(aiming)}
        raise AssertionError(f"unexpected diagnostic command: {command}")

    def _host(self):
        aiming=self.attached and (abs(self.axes[2])+abs(self.axes[3])>.01)
        pad=0xBFFF if self.attached and self.buttons&1 else 0xFFFF
        return {"collection_mode":1,"controllers":int(self.attached),"virtual_probe":int(self.attached),
                "modern":1,"gameplay":1,"aim_owned":int(aiming),"pad_word":pad,"axes":self.axes}


class StrictInputProbeTests(unittest.TestCase):
    def setUp(self):
        sleep=patch('strict_input_probe.time.sleep');sleep.start();self.addCleanup(sleep.stop)

    def test_exact_button_camera_and_detach(self):
        client=FakeClient();report=run_probe(client)
        self.assertEqual(report['status'],'passed')
        self.assertTrue(report['checks']['a_reached_guest'])
        self.assertTrue(report['checks']['guest_camera_applied'])
        self.assertFalse(report['physical_controls_qualified'])
        self.assertFalse(client.attached)

    def test_wrong_button_and_stalled_camera_reject_and_retain_samples(self):
        for options,message,sample in ((dict(guest_button=0x7FFF),'exact active-low jump state','a_down'),
                                       (dict(camera_stalled=True),'guest camera update','right_aim')):
            with self.subTest(options=options),tempfile.TemporaryDirectory() as directory:
                client=FakeClient(**options);output=Path(directory)/'input.json'
                with self.assertRaisesRegex(RuntimeError,message):run_probe(client,output)
                saved=json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(saved['status'],'failed');self.assertIn(sample,saved)
                self.assertFalse(client.attached)

    def test_attach_reply_failure_still_detaches_device(self):
        class ReplyFailure(FakeClient):
            def query(self,command,**kwargs):
                result=super().query(command,**kwargs)
                if command=='collection_input' and kwargs.get('enable')==1:
                    raise OSError('lost attach reply')
                return result
        client=ReplyFailure()
        with self.assertRaisesRegex(OSError,'lost attach reply'):run_probe(client)
        self.assertFalse(client.attached)

    def test_existing_virtual_device_is_not_fresh_acceptance(self):
        client=FakeClient();client.attached=True
        with self.assertRaisesRegex(RuntimeError,'fresh virtual device'):run_probe(client)
        self.assertTrue(client.attached) # The failed check must not detach a device it did not create.


if __name__=='__main__':unittest.main()
