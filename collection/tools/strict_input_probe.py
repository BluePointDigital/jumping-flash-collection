"""Strict Robbit SDL-input acceptance check for a visible guarded gameplay scene."""
import json
import time
from pathlib import Path


def _truth(value):
    return value is True or (type(value) is int and value == 1)


def _pad_word(value):
    if isinstance(value, str):
        return int(value[2:], 16) if value.lower().startswith("0x") else int(value, 16)
    return int(value) & 0xFFFF


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _wait_sample(client, frames=3, timeout=3.0):
    first = client.query("frame")["frame"]
    target = first + frames
    deadline = time.monotonic() + timeout
    while client.query("frame")["frame"] < target:
        if time.monotonic() >= deadline:
            raise TimeoutError("guest frame did not advance during functional input check")
        time.sleep(.025)
    return {
        "host": client.query("collection_input"),
        "guest": client.query("pad_status"),
    }


def _pad(sample):
    return _pad_word(sample["guest"]["slot0"]["buttons"])


def _host_neutral(sample):
    return sample["host"].get("pad_word") == 65535


def _guarded_gameplay(host):
    return _truth(host.get("collection_mode")) and _truth(host.get("modern")) and _truth(host.get("gameplay"))


def _desktop_guard(status, expected=None):
    _require(_truth(status.get("supported")) and _truth(status.get("modern")) and _truth(status.get("gameplay")),
             "Robbit desktop status is not in supported modern gameplay")
    profile = status.get("control_profile")
    changes = status.get("profile_changes")
    _require(isinstance(profile, str) and bool(profile), "Robbit control profile identity is missing")
    _require(type(changes) is int and changes >= 0, "Robbit profile-change counter is missing or invalid")
    if expected is not None:
        _require((profile, changes) == expected, "Robbit control profile changed during functional input check")
    return profile, changes


_ROBBIT_MEADOW_PROFILE = "EVENT/00/M01.PEX"


def guard_robbit_meadow_profile(client, expected=None):
    """Pin native position reads to the supported M01/Meadow scene only."""
    pin = _desktop_guard(client.query("robbit_desktop_status"), expected)
    _require(pin[0] == _ROBBIT_MEADOW_PROFILE,
             "native Robbit position sampling is supported only for EVENT/00/M01.PEX")
    return pin


def sample_robbit_meadow_position(client, expected=None):
    """Read player words only while the exact guarded Meadow profile is stable."""
    pin = guard_robbit_meadow_profile(client, expected)
    sample = client.query("mem_words", addr="800dbc00", count=6)
    words = sample.get("words") if isinstance(sample, dict) else None
    _require(isinstance(words, list) and len(words) == 6,
             "native Meadow position sample returned an invalid memory window")
    guard_robbit_meadow_profile(client, pin)
    return {"profile_pin": pin, "words": words}


def _counter(status, name):
    value = status.get(name)
    _require(type(value) is int and value >= 0, f"Robbit desktop {name} is missing or invalid")
    return value


def _set(client, *, enable=1, buttons=0, lx=0, ly=0, rx=0, ry=0, lt=0, rt=0):
    return client.query("collection_input", enable=enable, buttons=buttons,
                        lx=lx, ly=ly, rx=rx, ry=ry, lt=lt, rt=rt)


def run_probe(client, output=None):
    report = {
        "schema": 3,
        "method": "Visible guarded Robbit Meadow: exact fresh A, release, applied right-stick camera update, detach/reset",
        "physical_controls_qualified": False,
        "checks": {},
        "errors": [],
    }
    attached = False
    failure = None
    try:
        before = client.query("collection_input")
        _require(_guarded_gameplay(before), "input test requires collection mode, modern controls, and guarded Meadow gameplay")
        _require(not _truth(before.get("virtual_probe")), "input test requires a fresh virtual device")
        desktop_before = client.query("robbit_desktop_status")
        profile_pin = _desktop_guard(desktop_before)
        report["scene_before"] = {"host": before, "desktop": desktop_before}
        report["profile_pin"] = {"control_profile": profile_pin[0], "profile_changes": profile_pin[1]}

        attached = True
        _set(client, buttons=0)
        neutral = _wait_sample(client, frames=4)
        report["neutral"] = neutral
        _require(_truth(neutral["host"].get("virtual_probe")), "fresh virtual gamepad did not register")
        _require(_guarded_gameplay(neutral["host"]), "Meadow gameplay guard was lost after virtual-device attach")
        _desktop_guard(client.query("robbit_desktop_status"), profile_pin)
        _require(_host_neutral(neutral) and _pad(neutral) == 0xFFFF, "fresh neutral sample did not re-arm to released input")
        _require(not _truth(neutral["host"].get("aim_owned")), "aim ownership was already active before the fresh right-stick sample")
        report["checks"]["fresh_device_and_release_gate"] = True

        _set(client, buttons=1 << 0)  # SDL_GAMEPAD_BUTTON_SOUTH / A; fresh edge after neutral frames.
        a_down = _wait_sample(client, frames=3)
        report["a_down"] = a_down
        _require(_truth(a_down["host"].get("virtual_probe")) and _guarded_gameplay(a_down["host"]),
                 "virtual A sample left the registered guarded gameplay scene")
        _require(_pad_word(a_down["host"].get("pad_word", -1)) == 0xBFFF and _pad(a_down) == 0xBFFF,
                 "virtual A did not produce the exact active-low jump state 0xBFFF on host and guest")
        _desktop_guard(client.query("robbit_desktop_status"), profile_pin)
        report["checks"]["a_reached_guest"] = True

        _set(client, buttons=0)
        a_release = _wait_sample(client, frames=3)
        report["a_release"] = a_release
        _require(_host_neutral(a_release) and _pad(a_release) == 0xFFFF,
                 "virtual A release did not clear host and guest button state")
        _require(not _truth(a_release["host"].get("aim_owned")), "A/release sequence unexpectedly acquired aim ownership")
        desktop_before_aim = client.query("robbit_desktop_status")
        _desktop_guard(desktop_before_aim, profile_pin)
        camera_updates_before = _counter(desktop_before_aim, "camera_updates")
        yaw_before = desktop_before_aim.get("yaw")
        pitch_before = desktop_before_aim.get("pitch")
        _require(type(yaw_before) is int and type(pitch_before) is int, "Robbit yaw/pitch status is missing or invalid")
        report["checks"]["a_release_reached_guest"] = True

        _set(client, buttons=0, rx=24576, ry=-16384)
        right_aim = _wait_sample(client, frames=4)
        report["right_aim"] = right_aim
        axes = right_aim["host"].get("axes")
        _require(_guarded_gameplay(right_aim["host"]), "Meadow gameplay guard was lost during right-aim sample")
        _require(_truth(right_aim["host"].get("aim_owned")), "right-stick aim was not accepted by the focused gameplay input path")
        _require(isinstance(axes, list) and len(axes) == 6 and axes[2] > .25 and axes[3] < -.25,
                 "right-stick axes did not arrive with the requested signs/magnitudes")
        desktop_after_aim = client.query("robbit_desktop_status")
        right_aim.update(desktop_before=desktop_before_aim, desktop_after=desktop_after_aim)
        _desktop_guard(desktop_after_aim, profile_pin)
        _require(_counter(desktop_after_aim, "camera_updates") > camera_updates_before,
                 "right-stick ownership did not produce a guest camera update")
        _require(type(desktop_after_aim.get("yaw")) is int and desktop_after_aim["yaw"] != yaw_before,
                 "right-stick did not change guest camera yaw")
        _require(type(desktop_after_aim.get("pitch")) is int and desktop_after_aim["pitch"] != pitch_before,
                 "right-stick did not change guest camera pitch")
        report["checks"]["right_aim_owned"] = True
        report["checks"]["guest_camera_applied"] = True

        detached_reply = _set(client, enable=0)
        attached = False
        detached = _wait_sample(client, frames=4)
        report["detached"] = {"reply": detached_reply, **detached}
        _desktop_guard(client.query("robbit_desktop_status"), profile_pin)
        _require(not _truth(detached["host"].get("virtual_probe")), "virtual probe device remained attached")
        _require(not _truth(detached["host"].get("aim_owned")), "detach did not reset aim ownership")
        _require(_host_neutral(detached) and _pad(detached) == 0xFFFF,
                 "detach/reset left a synthetic button held")
        report["checks"]["detach_and_reset"] = True
        report["status"] = "passed"
    except Exception as error:
        failure = error
        report["status"] = "failed"
        report["errors"].append(repr(error))
    finally:
        if attached:
            try:
                report["cleanup_detach"] = _set(client, enable=0)
                attached = False
            except Exception as error:
                report["errors"].append("cleanup detach: " + repr(error))
                report["status"] = "failed"
        if output is not None:
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if failure is not None:
        raise failure
    if report["status"] != "passed":
        raise RuntimeError("functional input cleanup did not complete")
    return report


def probe_controls(port, output):
    from diagnostics import Client
    return run_probe(Client(port), output)
