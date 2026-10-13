import os, select, time, sys
# log every HID report from both receiver interfaces (plain motion is only counted)
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 120
fds = {os.open(p, os.O_RDONLY | os.O_NONBLOCK): p for p in ('/dev/hidraw0', '/dev/hidraw1')}
t0 = time.monotonic(); moves = 0
while time.monotonic() - t0 < dur:
    r, _, _ = select.select(list(fds), [], [], 0.2)
    for fd in r:
        try: d = os.read(fd, 64)
        except BlockingIOError: continue
        if fds[fd].endswith('0') and d[0] == 0:   # motion with no buttons pressed
            moves += 1; continue
        print(f't={time.monotonic()-t0:8.3f}s {fds[fd][-7:]} {d.hex(" ")}', flush=True)
print('motion reports:', moves)
