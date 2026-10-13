#!/usr/bin/env python3
"""CLI configurator for the Redragon M901P-KS (Compx 25a7:fa07 / 25a7:fa08) on Linux.

Protocol reverse-engineered from the vendor Windows driver (OemDrv.exe), see PROGRESS.md.

  host -> mouse : HID feature report 0x08, 16 bytes: cmd, 0, addrHi, addrLo, len, data[10], chk
  mouse -> host : HID input report 0x09, 16 bytes: cmd, status(0=ok), addrHi, addrLo, len, data[10], chk
  chk = (0x55 - sum(report incl. id)) & 0xff

Settings live in an on-board EEPROM (cmd 0x08 = read, cmd 0x07 = write).
"""
import argparse
import fcntl
import glob
import json
import os
import select
import sys
import time

VID = 0x25A7
PIDS = (0xFA07, 0xFA08)

CMD_HANDSHAKE = 0x01
CMD_STATUS = 0x02
CMD_WRITE = 0x07
CMD_READ = 0x08

ADDR_DPI = 0x0C
ADDR_DPI_COLOR = 0x2C
ADDR_MATRIX = 0x60
ADDR_KEYDATA = 0x100       # + 0x20 * matrix index
MACRO_ADDRS = [0x300 + 0x180 * i for i in range(16)]
EEPROM_DUMP_END = 0x1B00   # last macro block (0x1980) + 0x180

# Physical button number (as in the Windows UI: 1-12 side grid, 13 L, 14 R, 15 M, 16 fire)
# -> index in the on-board key matrix.
BUTTON_TO_MATRIX = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 8, 8: 9, 9: 12, 10: 13,
                    11: 14, 12: 15, 13: 7, 14: 6, 15: 10, 16: 11}
BUTTON_ALIASES = {"left": 13, "right": 14, "middle": 15, "fire": 16}

MOUSE_BUTTONS = {"left": 0x01, "right": 0x02, "middle": 0x04, "back": 0x08, "forward": 0x10}
SPECIALS = {
    "disable": (0x00, 0x00, 0x00),
    "dpi-up": (0x02, 0x02, 0x00),
    "dpi-down": (0x02, 0x03, 0x00),
    "dpi-loop": (0x02, 0x01, 0x00),
}
MODIFIERS = {"ctrl": 0x01, "lctrl": 0x01, "shift": 0x02, "lshift": 0x02,
             "alt": 0x04, "lalt": 0x04, "win": 0x08, "super": 0x08, "meta": 0x08, "gui": 0x08}
MACRO_MODIFIERS = dict(MODIFIERS, rctrl=0x10, rshift=0x20, ralt=0x40, altgr=0x40)
MACRO_MAX_EVENTS = (0x180 - 0x20 - 4) // 5   # 70
# matrix byte 2 for macros: N = play N times, or one of these loop modes
# Loop modes (verified on device): 0xFE loops while the button is held and stops on release.
# 0xFF keeps looping after release (driver: "cycle until any key pressed"); in testing it ran until power-off.
MACRO_LOOP_FF = 0xFF
MACRO_LOOP_FE = 0xFE
MEDIA = {"play": 0xCD, "playpause": 0xCD, "stop": 0xB7, "prev": 0xB6, "next": 0xB5,
         "volup": 0xE9, "voldown": 0xEA, "mute": 0xE2, "mediaselect": 0x183, "mail": 0x18A,
         "calc": 0x192, "computer": 0x194, "search": 0x221, "home": 0x223, "browser-back": 0x224,
         "browser-forward": 0x225, "browser-stop": 0x226, "refresh": 0x227, "favorites": 0x22A}

# HID keyboard usage IDs
KEYS = {chr(ord("a") + i): 0x04 + i for i in range(26)}
KEYS.update({str(i): 0x1D + i for i in range(1, 10)})
KEYS.update({"0": 0x27, "enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B,
             "space": 0x2C, "minus": 0x2D, "-": 0x2D, "equal": 0x2E, "=": 0x2E,
             "leftbrace": 0x2F, "[": 0x2F, "rightbrace": 0x30, "]": 0x30, "backslash": 0x31,
             "\\": 0x31, "semicolon": 0x33, ";": 0x33, "apostrophe": 0x34, "'": 0x34,
             "grave": 0x35, "`": 0x35, "comma": 0x36, ",": 0x36, "dot": 0x37, ".": 0x37,
             "slash": 0x38, "/": 0x38, "capslock": 0x39, "printscreen": 0x46,
             "scrolllock": 0x47, "pause": 0x48, "insert": 0x49, "home": 0x4A,
             "pageup": 0x4B, "delete": 0x4C, "end": 0x4D, "pagedown": 0x4E, "right": 0x4F,
             "left": 0x50, "down": 0x51, "up": 0x52, "numlock": 0x53, "kp/": 0x54,
             "kp*": 0x55, "kp-": 0x56, "kp+": 0x57, "kpenter": 0x58, "kp.": 0x63,
             "menu": 0x65})
KEYS.update({f"f{i}": 0x3A + i - 1 for i in range(1, 13)})
KEYS.update({f"f{i}": 0x68 + i - 13 for i in range(13, 25)})
KEYS.update({f"kp{i}": 0x59 + i - 1 for i in range(1, 10)})
KEYS["kp0"] = 0x62
KEY_NAMES = {}
for _n, _c in KEYS.items():
    KEY_NAMES.setdefault(_c, _n)


def chk(data):
    return (0x55 - sum(data)) & 0xFF


# ---------------------------------------------------------------- device I/O

def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("H") << 8) | nr


def HIDIOCSFEATURE(size):
    return _ioc(3, 0x06, size)


def find_hidraw():
    """Return the hidraw node of the vendor interface (the one with report IDs 8/9)."""
    found = []
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(os.path.join(node, "device/uevent")).read()
        except OSError:
            continue
        hid_id = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_ID=")), "")
        try:
            _bus, vid, pid = (int(x, 16) for x in hid_id.split(":"))
        except ValueError:
            continue
        if vid != VID or pid not in PIDS:
            continue
        desc = open(os.path.join(node, "device/report_descriptor"), "rb").read()
        # vendor feature report 8: "85 08" present in descriptor
        if b"\x85\x08" in desc:
            found.append("/dev/" + os.path.basename(node))
    return found


class Mouse:
    def __init__(self, path=None, verbose=False):
        if path is None:
            nodes = find_hidraw()
            if not nodes:
                sys.exit("M901P-KS not found (looking for 25a7:fa07/fa08 with vendor report 8)")
            path = nodes[0]
        self.path = path
        self.verbose = verbose
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            sys.exit(f"permission denied on {path}: install 70-m901p-ks.rules (see README.md) or run as root")

    def close(self):
        os.close(self.fd)

    def _drain(self):
        while True:
            try:
                os.read(self.fd, 64)
            except BlockingIOError:
                return

    def send(self, payload):
        payload = bytes(payload)[:15].ljust(15, b"\0")
        buf = bytearray(b"\x08" + payload)
        buf.append(chk(buf))
        if self.verbose:
            print(">>", buf.hex(" "), file=sys.stderr)
        fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(buf)), bytes(buf))

    def recv(self, cmd, timeout=1.0):
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return None
            r, _, _ = select.select([self.fd], [], [], left)
            if not r:
                return None
            try:
                rep = os.read(self.fd, 64)
            except BlockingIOError:
                continue
            if self.verbose:
                print("<<", rep.hex(" "), file=sys.stderr)
            if len(rep) >= 17 and rep[0] == 0x09 and rep[1] == cmd:
                return rep[1:17]

    def command(self, payload, retries=3):
        for _ in range(retries):
            self._drain()
            self.send(payload)
            resp = self.recv(payload[0])
            if resp is not None:
                return resp
            time.sleep(0.1)
        raise IOError(f"no response to command 0x{payload[0]:02x}")

    def read(self, addr, length):
        out = bytearray()
        while length > 0:
            n = min(10, length)
            resp = self.command([CMD_READ, 0, addr >> 8, addr & 0xFF, n])
            if resp[1] != 0:
                raise IOError(f"read error at 0x{addr:04x}: status {resp[1]}")
            out += resp[5:5 + n]
            addr += n
            length -= n
        return bytes(out)

    def write(self, addr, data):
        data = bytes(data)
        while data:
            n = min(10, len(data))
            resp = self.command([CMD_WRITE, 0, addr >> 8, addr & 0xFF, n] + list(data[:n]))
            if resp[1] != 0:
                raise IOError(f"write error at 0x{addr:04x}: status {resp[1]}")
            addr += n
            data = data[n:]

    def handshake(self):
        r = [1, 2, 3, 4]
        resp = self.command([CMD_HANDSHAKE, 0, 0, 0, 4] + r)
        return resp


# ---------------------------------------------------------------- encoding

def entry(b0, b1, b2):
    return bytes([b0, b1, b2, chk([b0, b1, b2])])


def parse_combo(spec):
    """'ctrl+shift+a' -> keyboard event block (without count/checksum)."""
    mods, key = 0, None
    parts = spec.lower().split("+")
    # a trailing '+' belongs to the key name: "kp+", "ctrl+kp+"
    while "" in parts:
        i = parts.index("")
        if i == 0:
            raise ValueError(f"bad key combo '{spec}'")
        parts[i - 1] += "+"
        del parts[i]
    for part in parts:
        part = part.strip()
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif part in KEYS:
            if key is not None:
                raise ValueError(f"only one non-modifier key allowed in '{spec}'")
            key = KEYS[part]
        elif part.startswith("0x"):
            key = int(part, 16)
        else:
            raise ValueError(f"unknown key '{part}' (try `m901.py keys`)")
    ev = []
    for bit in (1, 2, 4, 8):
        if mods & bit:
            ev.append((0x80, bit, 0))
    if key is not None:
        ev.append((0x81, key, 0))
    # firmware sends 0x8x events on button down and 0x4x on button up (verified: combos can be held);
    # release the key before its modifiers
    if key is not None:
        ev.append((0x41, key, 0))
    for bit in (8, 4, 2, 1):
        if mods & bit:
            ev.append((0x40, bit, 0))
    if not ev:
        raise ValueError(f"empty key combo '{spec}'")
    return ev


def keydata_block(events):
    blob = bytearray([len(events)])
    for e in events:
        blob += bytes(e)
    blob.append(chk(blob))
    return bytes(blob)


def parse_action(spec):
    """Return (matrix_entry_bytes, keydata_block_or_None)."""
    s = spec.lower()
    if s in SPECIALS:
        return entry(*SPECIALS[s]), None
    if s in MOUSE_BUTTONS:
        return entry(0x01, MOUSE_BUTTONS[s], 0), None
    kind, _, arg = s.partition(":")
    if kind == "mouse" and arg in MOUSE_BUTTONS:
        return entry(0x01, MOUSE_BUTTONS[arg], 0), None
    if kind == "media":
        code = MEDIA.get(arg) if arg in MEDIA else int(arg, 0)
        ev = [(0x82, code & 0xFF, code >> 8), (0x42, code & 0xFF, code >> 8)]
        return entry(0x05, 0, 0), keydata_block(ev)
    if kind == "key":
        return entry(0x05, 0, 0), keydata_block(parse_combo(arg))
    if kind == "fire":
        interval, _, count = arg.partition(",")
        return entry(0x04, int(interval, 0), int(count or "3", 0)), None
    if kind == "raw":
        b = [int(x, 0) for x in arg.split(",")]
        return entry(*b[:3]), None
    raise ValueError(f"unknown action '{spec}'")


def describe_entry(e, keydata=None):
    b0, b1, b2, c = e
    bad = "" if chk([b0, b1, b2]) == c else " [bad checksum]"
    if b0 == 0x00:
        return "disable" + bad
    if b0 == 0x01:
        names = [n for n, m in MOUSE_BUTTONS.items() if b1 & m]
        return "mouse:" + "+".join(names or [hex(b1)]) + bad
    if b0 == 0x02:
        return {1: "dpi-loop", 2: "dpi-up", 3: "dpi-down"}.get(b1, f"dpi?{b1:#x}") + bad
    if b0 == 0x05:
        return describe_keydata(keydata) + bad
    if b0 == 0x04:
        return f"fire:{b1},{b2} (interval={b1}, repeat={b2})" + bad
    if b0 == 0x06:
        return f"macro slot {b1} ({describe_repeat(b2)})" + bad
    return f"raw:{b0:#04x},{b1:#04x},{b2:#04x}" + bad


def describe_keydata(blob):
    if not blob:
        return "key:?"
    n = blob[0]
    if n == 0 or n > 9:
        return f"key:? ({blob[:8].hex(' ')})"
    evs = [blob[1 + 3 * i:4 + 3 * i] for i in range(n)]
    parts = []
    for t, c, h in evs:
        if t == 0x80:
            parts += [m for m, bit in (("ctrl", 1), ("shift", 2), ("alt", 4), ("win", 8)) if c & bit]
        elif t == 0x81:
            parts.append(KEY_NAMES.get(c, f"0x{c:02x}"))
        elif t == 0x82:
            code = c | h << 8
            name = next((k for k, v in MEDIA.items() if v == code), f"0x{code:x}")
            return f"media:{name}"
    return "key:" + "+".join(parts)


# ---------------------------------------------------------------- macros
#
# slot (0x180 bytes at MACRO_ADDRS[matrix index]):
#   [0] name byte length, [1..30] UTF-16LE name, [0x1f] event count,
#   from 0x20: events of 5 bytes (0x80|type press / 0x40|type release, code, 0, delay_hi, delay_lo),
#   then checksum (over count+events only, NOT the name) and 3 zero bytes. type 0 = modifier bits, 1 = keyboard (HID usage), 4 = mouse button.
#   Delay (ms, big endian) is the pause after the event; the driver never writes less than 3.
#   Matrix entry: 06 <slot> <repeat>.

def macro_target(name):
    """name -> (type, code)"""
    n = name.lower()
    if n in MACRO_MODIFIERS:
        return 0, MACRO_MODIFIERS[n]
    if n.startswith("mouse:") and n[6:] in MOUSE_BUTTONS:
        return 4, MOUSE_BUTTONS[n[6:]]
    if n in KEYS:
        return 1, KEYS[n]
    if n.startswith("0x"):
        return 1, int(n, 16)
    raise ValueError(f"unknown key '{name}' in macro (try `m901.py keys`)")


def _split_combo(tok):
    parts = tok.split("+")
    while "" in parts:              # "kp+" / "ctrl+kp+"
        i = parts.index("")
        if i == 0:
            raise ValueError(f"bad macro token '{tok}'")
        parts[i - 1] += "+"
        del parts[i]
    return parts


def parse_macro(text, delay=20):
    """Macro script -> list of (press, type, code, delay_ms).

    Tokens (whitespace or comma separated):
      a            tap: press + release        ctrl+shift+t  combo tap
      +a / -a      press only / release only   mouse:left    mouse button (also right/middle/back/forward)
      150 / 150ms  pause after the previous event (replaces the default delay)
    """
    events = []
    for tok in text.replace(",", " ").split():
        t = tok.lower()
        num = t[:-2] if t.endswith("ms") else t
        if num.isdigit():
            if not events:
                raise ValueError("macro cannot start with a delay")
            p, ty, c, _ = events[-1]
            events[-1] = (p, ty, c, int(num))
        elif t[0] in "+-" and len(t) > 1:
            ty, c = macro_target(t[1:])
            events.append((t[0] == "+", ty, c, delay))
        else:
            targets = [macro_target(x) for x in _split_combo(t)]
            events += [(True, ty, c, delay) for ty, c in targets]
            events += [(False, ty, c, delay) for ty, c in reversed(targets)]
    if not events:
        raise ValueError("empty macro")
    if len(events) > MACRO_MAX_EVENTS:
        raise ValueError(f"macro has {len(events)} events, max is {MACRO_MAX_EVENTS}")
    return events


def macro_block(events, name="macro"):
    name_b = name.encode("utf-16-le")[:30]
    blob = bytearray(0x20)
    blob[0] = len(name_b)
    blob[1:1 + len(name_b)] = name_b
    blob[0x1F] = len(events)
    for press, ty, code, d in events:
        d = max(3, min(d, 0xFFFF))
        blob += bytes([(0x80 if press else 0x40) | ty, code, 0, d >> 8, d & 0xFF])
    # the driver computes the checksum before it inserts the name, so the name is not covered
    blob.append(chk(blob[0x1F:]))
    blob += b"\0\0\0"
    return bytes(blob)


def describe_macro(blob):
    if not blob or blob[0x1F] in (0, 0xFF):
        return "(empty)", ""
    nlen = blob[0] if blob[0] <= 30 else 0
    name = blob[1:1 + nlen].decode("utf-16-le", "replace")
    n = blob[0x1F]
    out = []
    for i in range(min(n, MACRO_MAX_EVENTS)):
        f, code, _z, dh, dl = blob[0x20 + 5 * i:0x25 + 5 * i]
        ty = f & 7
        if ty == 0:
            label = next((k for k, v in MACRO_MODIFIERS.items() if v == code), f"mod{code:#x}")
        elif ty == 4:
            label = "mouse:" + next((k for k, v in MOUSE_BUTTONS.items() if v == code), hex(code))
        else:
            label = KEY_NAMES.get(code, f"0x{code:02x}")
        d = dh << 8 | dl
        out.append(("+" if f & 0x80 else "-") + label + ("" if d <= 3 else f" {d}"))
    end = 0x20 + 5 * n
    ok = end < len(blob) and blob[end] == chk(blob[0x1F:end])
    return name, " ".join(out) + ("" if ok else "  [bad checksum]")


def describe_repeat(rr):
    return {MACRO_LOOP_FF: "loop until any key (continues after release)",
            MACRO_LOOP_FE: "loop while held"}.get(rr, f"x{rr}")


# ---------------------------------------------------------------- commands

def resolve_button(b):
    b = b.lower()
    if b in BUTTON_ALIASES:
        return BUTTON_ALIASES[b]
    n = int(b)
    if n not in BUTTON_TO_MATRIX:
        raise ValueError("button must be 1-16 or left/right/middle/fire")
    return n


def cmd_show(m, args):
    matrix = m.read(ADDR_MATRIX, 64)
    for btn in sorted(BUTTON_TO_MATRIX):
        idx = BUTTON_TO_MATRIX[btn]
        e = matrix[idx * 4:idx * 4 + 4]
        kd = m.read(ADDR_KEYDATA + 0x20 * idx, 0x20) if e[0] == 0x05 else None
        label = {13: "left", 14: "right", 15: "middle", 16: "fire"}.get(btn, f"side {btn}")
        print(f"button {btn:2d} ({label:7s}) [{e.hex(' ')}]  {describe_entry(e, kd)}")
        if e[0] == 0x06 and e[1] < len(MACRO_ADDRS):
            name, script = describe_macro(m.read(MACRO_ADDRS[e[1]], 0x180))
            print(f"      macro '{name}': {script}")


def cmd_set(m, args):
    btn = resolve_button(args.button)
    idx = BUTTON_TO_MATRIX[btn]
    e, kd = parse_action(args.action)
    if kd is not None:
        # pad the 32-byte slot with 0xff (erased state) so no stale bytes from a longer old entry remain
        m.write(ADDR_KEYDATA + 0x20 * idx, kd.ljust(0x20, b"\xff"))
    m.write(ADDR_MATRIX + 4 * idx, e)
    print(f"button {btn} -> {args.action}  (matrix[{idx}] = {e.hex(' ')}"
          + (f", keydata = {kd.hex(' ')}" if kd else "") + ")")


def cmd_macro(m, args):
    btn = resolve_button(args.button)
    idx = BUTTON_TO_MATRIX[btn]
    text = open(args.file).read() if args.file else " ".join(args.script)
    events = parse_macro(text, args.delay)
    if args.while_held:
        rr = MACRO_LOOP_FE
    elif args.until_key:
        rr = MACRO_LOOP_FF
        print("warning: this macro keeps looping after the button is released; in testing only switching the "
              "mouse off stopped it", file=sys.stderr)
    else:
        if not 1 <= args.repeat <= 0xFD:
            raise ValueError("--repeat must be 1..253")
        rr = args.repeat
    blob = macro_block(events, args.name)
    if args.verbose:
        print("macro block:", blob.hex(" "), file=sys.stderr)
    # fill the rest of the slot with 0xff (erased state) so nothing from an older, longer macro remains
    m.write(MACRO_ADDRS[idx], blob.ljust(0x180, b"\xff"))
    # byte 1 = macro slot; the driver uses the button's matrix index (OemDrv.exe @0x40b97a)
    e = entry(0x06, idx, rr)
    m.write(ADDR_MATRIX + 4 * idx, e)
    name, script = describe_macro(blob)
    print(f"button {btn} -> macro '{name}' ({describe_repeat(rr)}, {len(events)} events): {script}")


def cmd_dump(m, args):
    addr, length = int(args.addr, 0), int(args.length, 0)
    data = m.read(addr, length)
    for i in range(0, len(data), 16):
        print(f"{addr + i:04x}: {data[i:i + 16].hex(' ')}")


def cmd_backup(m, args):
    end = int(args.end, 0)
    data = bytearray()
    for a in range(0, end, 10):
        data += m.read(a, min(10, end - a))
    with open(args.file, "wb") as f:
        f.write(data)
    print(f"saved {len(data)} bytes to {args.file}")


def cmd_restore(m, args):
    data = open(args.file, "rb").read()
    start = int(args.start, 0)
    end = int(args.end, 0) if args.end else len(data)
    m.write(start, data[start:end])
    print(f"restored 0x{start:04x}..0x{end:04x}")


def cmd_writeraw(m, args):
    m.write(int(args.addr, 0), bytes(int(x, 16) for x in args.bytes))


def cmd_raw(m, args):
    resp = m.command([int(x, 16) for x in args.bytes])
    print(resp.hex(" "))


def cmd_keys(_m, _args):
    print("modifiers:", ", ".join(sorted(MODIFIERS)))
    print("keys:", " ".join(sorted(KEYS, key=lambda k: (len(k), k))))
    print("media:", ", ".join(sorted(MEDIA)))
    print("mouse:", ", ".join(MOUSE_BUTTONS))
    print("special:", ", ".join(SPECIALS))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-d", "--device", help="hidraw node (auto-detected)")
    p.add_argument("-v", "--verbose", action="store_true", help="print raw reports")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list detected hidraw nodes")
    sub.add_parser("show", help="show current button mapping")
    s = sub.add_parser("set", help="remap a button",
                       epilog="actions: key:ctrl+c, key:f5, media:volup, left/right/middle/back/forward, "
                              "dpi-up, dpi-down, dpi-loop, disable, fire:INTERVAL,REPEAT (factory fire:20,3), raw:b0,b1,b2")
    s.add_argument("button", help="1-12 (side grid), 13/left, 14/right, 15/middle, 16/fire")
    s.add_argument("action")
    s = sub.add_parser("macro", help="assign a macro to a button", formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="script tokens: a (tap), ctrl+c (combo tap), +a (press), -a (release),\n"
                              "mouse:left|right|middle|back|forward, 150 or 150ms (pause after previous event)\n"
                              "example: m901.py macro 5 'ctrl+a 50 ctrl+c'   m901.py macro 6 --while-held mouse:left 30")
    s.add_argument("button")
    s.add_argument("script", nargs="*", help="macro script (or use -f)")
    s.add_argument("-f", "--file", help="read the script from a file")
    s.add_argument("--name", default="macro", help="macro name stored on the mouse (max 15 chars)")
    s.add_argument("--delay", type=int, default=20, help="default pause after each event in ms (default 20)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--repeat", type=int, default=1, help="play N times (default 1)")
    g.add_argument("--while-held", action="store_true", help="loop while the button is held (stops on release)")
    g.add_argument("--until-key", action="store_true",
                   help="CAUTION: keeps looping after release ('until any key pressed' in the Windows UI)")
    s = sub.add_parser("dump", help="hex dump EEPROM")
    s.add_argument("addr"); s.add_argument("length")
    s = sub.add_parser("backup", help="save EEPROM to file")
    s.add_argument("file"); s.add_argument("--end", default=hex(EEPROM_DUMP_END))
    s = sub.add_parser("restore", help="write EEPROM from a backup file")
    s.add_argument("file"); s.add_argument("--start", default="0"); s.add_argument("--end")
    s = sub.add_parser("write", help="write raw bytes to EEPROM: write 0x60 01 01 00 53")
    s.add_argument("addr"); s.add_argument("bytes", nargs="+")
    s = sub.add_parser("raw", help="send raw command payload (hex bytes) and print the reply")
    s.add_argument("bytes", nargs="+")
    sub.add_parser("keys", help="list key names")
    args = p.parse_args()

    if args.cmd == "keys":
        return cmd_keys(None, args)
    if args.cmd == "list":
        print("\n".join(find_hidraw()) or "not found")
        return
    m = Mouse(args.device, args.verbose)
    try:
        {"show": cmd_show, "set": cmd_set, "macro": cmd_macro, "dump": cmd_dump, "backup": cmd_backup,
         "restore": cmd_restore, "write": cmd_writeraw, "raw": cmd_raw}[args.cmd](m, args)
    except ValueError as e:
        sys.exit(str(e))
    finally:
        m.close()


if __name__ == "__main__":
    main()
