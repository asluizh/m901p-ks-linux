# SPDX-License-Identifier: GPL-2.0-or-later
import os, fcntl, select, time, sys
def chk(b): return (0x55 - sum(b)) & 0xff
def ioc(d, nr, size): return (d << 30) | (size << 16) | (ord('H') << 8) | nr
fd = os.open('/dev/hidraw1', os.O_RDWR | os.O_NONBLOCK)
mfd = os.open('/dev/hidraw0', os.O_RDONLY | os.O_NONBLOCK)
buf = bytearray(b'\x08' + bytes([8, 0, 0, 0x60, 10]).ljust(15, b'\0')); buf.append(chk(buf))
end = time.time() + 90; motion = 0; last = 0
while time.time() < end:
    if time.time() - last > 0.5:
        fcntl.ioctl(fd, ioc(3, 6, 17), bytes(buf)); last = time.time()
    r, _, _ = select.select([fd, mfd], [], [], 0.1)
    for f in r:
        try: d = os.read(f, 64)
        except BlockingIOError: continue
        if f == mfd:
            motion += 1
            if motion in (1, 50): print(f't={90-(end-time.time()):.1f} mouse motion seen ({motion})', flush=True)
        else:
            print(f't={90-(end-time.time()):.1f} vendor:', d.hex(' '), flush=True)
            if d[0] == 9 and d[1] == 8: print('READ OK'); sys.exit(0)
print('timeout, motion events:', motion)
