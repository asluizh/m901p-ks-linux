# SPDX-License-Identifier: GPL-2.0-or-later
# read-only: on each profile-switch notification (report 9, cmd 0x0a), record the active profile marker
# and which 0x100-blocks of the storage area (0x1b00-0x4000) are in use
import importlib.util, os, sys, time, select
s = importlib.util.spec_from_file_location('m', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'm901.py'))
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
dev = m.Mouse()
def state():
    hdr = dev.read(0, 2); a0 = dev.read(0xa0, 11)
    used = []
    for b in range(0x1b00, 0x4000, 0x100):
        head = dev.read(b, 2)
        if head != b'\xff\xff': used.append(f'{b:04x}:{head.hex()}')
    return f'active={hdr.hex(" ")} a0={a0.hex(" ")} stored=[{" ".join(used)}]'
print('start  ', state(), flush=True)
end = time.monotonic() + float(sys.argv[1]); n = 0
while time.monotonic() < end:
    r, _, _ = select.select([dev.fd], [], [], 0.5)
    if not r: continue
    try: rep = os.read(dev.fd, 64)
    except BlockingIOError: continue
    if rep[0] == 9 and rep[1] == 0x0a:
        n += 1; time.sleep(0.3)        # let the mouse finish copying
        print(f'press {n}: notify={rep[1:10].hex(" ")}  {state()}', flush=True)
