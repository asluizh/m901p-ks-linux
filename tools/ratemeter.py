# SPDX-License-Identifier: GPL-2.0-or-later
# read-only: count mouse reports per second (hidraw0) and mark profile switches (report 9 cmd 0x0a on hidraw1)
import os, select, time, sys
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 180
mfd = os.open('/dev/hidraw0', os.O_RDONLY | os.O_NONBLOCK)
vfd = os.open('/dev/hidraw1', os.O_RDONLY | os.O_NONBLOCK)
rates = {1: 1000, 2: 500, 4: 250, 8: 125}
t0 = time.monotonic(); sec = 0; count = 0
while time.monotonic() - t0 < dur:
    r, _, _ = select.select([mfd, vfd], [], [], 0.05)
    for fd in r:
        try: d = os.read(fd, 64)
        except BlockingIOError: continue
        if fd == mfd: count += 1
        elif d[0] == 9 and d[1] == 0x0a and d[6] & 0x02:
            code = d[8] & 0x0f
            print(f't={time.monotonic()-t0:6.1f}s  PROFILE SWITCH -> rate code {code} ({rates.get(code, "?")} Hz)', flush=True)
    now = int(time.monotonic() - t0)
    if now != sec:
        if count: print(f't={sec:4d}s  {count:5d} reports/s', flush=True)
        sec, count = now, 0
