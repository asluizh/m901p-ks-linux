# SPDX-License-Identifier: GPL-2.0-or-later
# read-only: save config areas + receiver status (feature report 6) to a file
import importlib.util, os, sys, fcntl
s = importlib.util.spec_from_file_location('m', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'm901.py'))
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
dev = m.Mouse()
buf = bytearray(64); buf[0] = 6
fcntl.ioctl(dev.fd, m._ioc(3, 0x07, 64), buf, True)        # HIDIOCGFEATURE
data = dev.read(0x0000, 0x300) + dev.read(0x2500, 0x300) + bytes(buf[:8])
open(sys.argv[1], 'wb').write(data)
print('status report 6:', bytes(buf[:8]).hex(' '))
print('byte 0x00:', data[0:2].hex(' '), ' 0xa0:', data[0xa0:0xab].hex(' '))
