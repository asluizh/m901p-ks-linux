# SPDX-License-Identifier: GPL-2.0-or-later
# read-only: on each profile switch, show button 12 (matrix idx 15) in the active area and in both profile slots
import importlib.util, os, sys, time, select
s = importlib.util.spec_from_file_location('m', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'm901.py'))
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
dev = m.Mouse()
IDX = 15
def btn(base):
    e = dev.read(base + m.ADDR_MATRIX + 4 * IDX, 4)
    if e == b'\xff' * 4: return 'empty'
    kd = dev.read(base + m.ADDR_KEYDATA + 0x20 * IDX, 0x20)
    return m.describe_entry(e, kd)
def state():
    rate = {1: 1000, 2: 500, 4: 250, 8: 125}.get(dev.read(0, 1)[0], '?')
    return f'active({rate} Hz): {btn(0)} | slot 0x1b00: {btn(0x1b00)} | slot 0x2500: {btn(0x2500)}'
print('start  ', state(), flush=True)
end = time.monotonic() + float(sys.argv[1]); n = 0
while time.monotonic() < end:
    r, _, _ = select.select([dev.fd], [], [], 0.5)
    if not r: continue
    try: rep = os.read(dev.fd, 64)
    except BlockingIOError: continue
    if rep[0] == 9 and rep[1] == 0x0a and rep[6] & 0x02:
        n += 1; time.sleep(0.3)
        print(f'switch {n}:', state(), flush=True)
