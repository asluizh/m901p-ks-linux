import os, select, time, sys
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 120
fd = os.open('/dev/hidraw1', os.O_RDONLY | os.O_NONBLOCK)
t0 = time.monotonic(); last = None
while time.monotonic() - t0 < dur:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        d = os.read(fd, 64); t = time.monotonic()
        if d[0] in (1, 5):
            dt = '' if last is None else f' (+{(t-last)*1000:.0f} ms)'
            print(f't={t-t0:8.3f}s {d.hex(" ")}{dt}', flush=True); last = t
