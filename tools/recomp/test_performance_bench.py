"""Check percentile math, route cadence and guaranteed input cleanup."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import io
s = importlib.util.spec_from_file_location("bench", Path(__file__).with_name("performance-bench.py"))
b = importlib.util.module_from_spec(s)
s.loader.exec_module(b)
assert b.summarize([30, 20, 10, 110]) == dict(count=4, mean_ms=42.5, p50_ms=20, p95_ms=110, p99_ms=110, max_ms=110, stalls_over_100_ms=1)
try:
    b.summarize([])
    raise AssertionError("empty samples accepted")
except RuntimeError:
    pass
class Client:
    def __init__(self): self.calls=[]
    def query(self, command, **args):
        self.calls.append((command,args))
        if command=="read_ram": return {"hex":"00"*12}
        return {"desktop": {"menu": False, "supported": True}} if command=="jf2_desktop_status" else {}
c=Client()
b.route(c,"booster",60)
steps=[a for cmd,a in c.calls if cmd=="input_route_append"]
assert sum(x["frames"] for x in steps)>=62*50
assert all(x["boost"]==int(x["buttons"]!=0xFFFF) for x in steps)
assert c.calls[0][0]=="input_route_clear" and c.calls[-1][0]=="input_route_start"
# An invalid timing reply must still release the diagnostic route and pad.
c=Client()
with patch.object(b,"route"), patch.object(b.time,"sleep"):
    try: b.measure(c,"street",1)
    except KeyError: pass
assert [x[0] for x in c.calls[-2:]]==["input_route_clear","clear_input"]
# Also exercise cleanup after measurement has started.
class Broken(Client):
    def query(self, command, **args):
        result=super().query(command,**args)
        if command=="frame_perf_samples":
            if args["after"]=="0": return {"samples":[[1,1,20]]}
            raise RuntimeError("lost socket")
        if command=="frame": return {"frame":1}
        return result
c=Broken()
with patch.object(b,"route"), patch.object(b.time,"sleep"):
    try: b.measure(c,"street",1)
    except RuntimeError: pass
assert [x[0] for x in c.calls[-2:]]==["input_route_clear","clear_input"]
print("PASS: percentile math, booster recipes and failed-measurement input cleanup")
class Starting(b.Client):
    def query(self, command, **args):
        self.id+=1
        if self.id<3: raise ConnectionRefusedError()
        return {"ok":True}
c=Starting(4392)
with patch.object(b.time,"sleep"): c.wait_ready()
assert c.id==3
class Socket:
    sent=[]
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def settimeout(self,*args): pass
    def sendall(self,data): self.sent.append(data)
    def makefile(self,*args): return io.BytesIO(b'{"id":1,"ok":true}\n')
sock=Socket()
with patch.object(b.socket,"create_connection",side_effect=[TimeoutError(),sock]), patch.object(b.time,"sleep"):
    b.Client(4392).query("input_route_append",frames=10,buttons=65535)
assert len(sock.sent)==1, "A connect retry must not duplicate a queued input step"
class Gap(Client):
    def query(self, command, **args):
        result=super().query(command,**args)
        if command=="frame_perf_samples":
            return {"samples":[[1,1,20]] if args["after"]=="0" else [[3,3,20]]}
        if command=="frame": return {"frame":1}
        if command=="audio_stats": return {"out":{"underruns":0}}
        return result
c=Gap()
with patch.object(b,"route"), patch.object(b.time,"sleep"), patch.object(b.time,"monotonic",side_effect=[0,0,0,1,1,1]):
    try:
        b.measure(c,"street",1)
        raise AssertionError("Missing timing samples accepted")
    except RuntimeError as error:
        assert "lost 1 timing samples" in str(error)
assert [x[0] for x in c.calls[-2:]]==["input_route_clear","clear_input"]
print("PASS: startup/connect retries do not repeat mutations; timing gaps reject acceptance")
