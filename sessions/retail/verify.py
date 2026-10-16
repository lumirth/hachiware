"""Retail gameplay and peer persistence from lumirth/pw at 6dc7bc0.

Layouts and sequences follow globals.h, records.h, pw_dowsing.c, pw_battle.c
and PeerFinalize. Firmware and EEPROM images are supplied by the caller.
"""
import json
from pathlib import Path
import wave

from sessions.runner import Observation, compare

ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def buttons(path, presses):
    lines = []
    for ms, button in presses:
        values = [int(button == n) for n in range(3)]
        lines += [f"{ms * 1000},buttons,{','.join(map(str, values))}",
                  f"{(ms + 250) * 1000},buttons,0,0,0"]
    path.write_text("\n".join(lines) + "\n")
    return path


def game(runner, name, state, inputs, checkpoint, end, edits=()):
    whole = runner.execute(name, end, restore=state, inputs=inputs, edits=edits, audio=True)
    prefix = runner.execute(name + "-before", checkpoint, restore=state, inputs=inputs, edits=edits)
    resumed = runner.execute(name + "-resumed", end, restore=prefix.artifact("state"), inputs=inputs)
    errors = compare(whole, resumed, prefix)
    require(not errors, f"{name}: {errors}")
    require(whole.report["counters"]["nv_commits"] > 0, f"{name}: no completed save")
    with wave.open(str(whole.directory / "audio.wav"), "rb") as audio:
        require(audio.getnchannels() == 1 and audio.getsampwidth() == 2 and audio.getframerate() == 48000,
                f"{name}: expected mono 48 kHz PCM16")
        require(any(audio.readframes(audio.getnframes())), f"{name}: silent audio")
    require(any(whole.data("pixels")), f"{name}: inactive display")
    ram = whole.data("ram")
    contrast = (ram[0x29] + ((ram[23] >> 3) & 15)) & 63
    require(whole.report["observations"]["display_contrast"] == contrast, f"{name}: contrast differs")
    require(ram[0x31] == 0, f"{name}: firmware did not return home")
    return whole


def play(runner, firmware, eeprom):
    runner.require("audio", "edit_ram")
    motion = ROOT / "walking.csv"
    boot = runner.execute("walking-boot", 4000, firmware=firmware, eeprom=eeprom, inputs=motion)
    walking = runner.execute("walking-earned", 61000, restore=boot.artifact("state"), inputs=motion)
    initial = int.from_bytes(boot.data("ram")[14:16], "big")
    earned = int.from_bytes(walking.data("ram")[14:16], "big")
    require(earned > initial and earned >= 3, "walking must earn at least three Watts")
    previous_item = walking.data("eeprom")[0xcebc:0xcebe]
    inputs = buttons(runner.output / "dowsing.csv", [
        (61000, 1), (61500, 0), (62000, 1), (62500, 2),
        (63000, 2), (63500, 1), (67000, 1)])
    dowsing = game(runner, "dowsing", walking.artifact("state"), inputs, 64000, 68500)
    remaining = (earned - 3).to_bytes(2, "big")
    require(dowsing.data("ram")[14:16] == remaining, "Dowsing must charge three Watts")
    saved = dowsing.data("eeprom")
    for address in (0x0156, 0x0256):
        require(saved[address + 14:address + 16] == remaining, "Dowsing charge must reach both saves")
    require(saved[0xcebc:0xcebe] != previous_item, "Dowsing reward must reach EEPROM")
    inputs = buttons(runner.output / "capture.csv", [
        (61000, 2), (61500, 1), (62000, 2), (62500, 1), (64750, 2),
        (65250, 2), (65750, 1), (71500, 1), (72000, 1), (72500, 1),
        (73000, 1), (73500, 0), (77500, 0), (81500, 1), (93250, 1)])
    capture = game(runner, "capture", walking.artifact("state"), inputs, 85000, 94750,
                   edits=[(0xf78e, (100).to_bytes(2, "big"))])
    require(capture.data("ram")[14:16] == bytes([0, 90]), "radar must charge ten Watts")
    saved, source = capture.data("eeprom"), eeprom.read_bytes()
    require(saved[0xce8c:0xce9c] == source[0x8f72:0x8f82], "captured encounter must reach EEPROM")
    require(saved[0xce8c:0xce8e] != bytes(2), "capture must contain a Pokemon")
    return {"name": "play", "earned_watts": earned, "dowsing": "pass", "capture": "pass"}


def peer_image(source, identity):
    data = bytearray(source)
    def checksum(start, length):
        data[start + length] = (1 + sum(data[start:start + length])) & 255
    for start in (0x83, 0x183):
        data[start:start + 40] = bytes([identity])*40
        checksum(start, 40)
    for start in (0xed, 0x1ed):
        require(data[start + 91] & 3 == 3, "peer save needs a walking Pokemon")
        data[start + 16:start + 56] = bytes([identity])*40
        checksum(start, 104)
    data[0xcc08:0xcc30] = bytes([identity])*40
    data[0xdc00:0xdc00 + 548*11] = bytes([255])*(548*11)
    return data


def link(runner, firmware, eeprom):
    runner.require("link")
    a, b = runner.output / "peer-a.bin", runner.output / "peer-b.bin"
    source = eeprom.read_bytes()
    a.write_bytes(peer_image(source, 0x21))
    b.write_bytes(peer_image(source, 0x42))
    left = buttons(runner.output / "peer-a.csv", [(4500, 1), (5000, 1)])
    right = buttons(runner.output / "peer-b.csv", [(4550, 1), (5050, 1)])
    whole = runner.execute("link", 12000, firmware=firmware, eeprom=a, inputs=left,
                           peer_eeprom=b, peer_input=right, delay_us=1, history=False)
    peer = whole.directory / "peer"
    other = Observation(peer, json.loads((peer / "session.json").read_text()))
    start = 0xdc00 + 548 + 8
    require(whole.data("eeprom")[start:start + 40] == bytes([0x42])*40,
            "first firmware must commit the received identity to history slot 1")
    require(other.data("eeprom")[start:start + 40] == bytes([0x21])*40,
            "second firmware must commit the received identity to history slot 1")
    require(int(other.report["end_raw"]) == (12000 << 64)//1000 and other.report["fault"] is None,
            "peer must complete the session")
    return {"name": "link", "optical_transitions": [whole.report["counters"]["ir_events"],
                                                        other.report["counters"]["ir_events"]]}
