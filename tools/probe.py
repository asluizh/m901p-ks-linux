# SPDX-License-Identifier: GPL-2.0-or-later
import os, fcntl, select, time, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')
import importlib.util
s = importlib.util.spec_from_file_location('m', os.path.dirname(os.path.abspath(__file__)) + '/../m901.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
def ioc(d, nr, size): return (d << 30) | (size << 16) | (ord('H') << 8) | nr
dev = sys.argv[1]
fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
payload = [int(x, 16) for x in sys.argv[2:]] or [8, 0, 0, 0x60, 10]
buf = bytearray(b'\x08' + bytes(payload).ljust(15, b'\0')); buf.append(m.chk(buf))
fcntl.ioctl(fd, ioc(3, 6, 17), bytes(buf)); print('sent', buf.hex(' '))
end = time.time() + 1.5
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.1)
    if r:
        try: print('read', os.read(fd, 64).hex(' '))
        except BlockingIOError: pass
for rid, ln in ((8, 17), (6, 8), (9, 17)):
    for nr, nm in ((7, 'GFEATURE'), (0x0a, 'GINPUT')):
        b = bytearray(64); b[0] = rid
        try:
            n = fcntl.ioctl(fd, ioc(3, nr, 64), b, True); print(nm, rid, n, b[:ln].hex(' '))
        except OSError as e: print(nm, rid, 'err', e)
