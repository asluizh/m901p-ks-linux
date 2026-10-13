# SPDX-License-Identifier: GPL-2.0-or-later
# read-only: dump EEPROM from START until the device reports an error or END is reached
import importlib.util, os, sys
s = importlib.util.spec_from_file_location('m', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'm901.py'))
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
start, end, out = int(sys.argv[1], 0), int(sys.argv[2], 0), sys.argv[3]
dev = m.Mouse()
data = bytearray(); a = start
try:
    while a < end:
        n = min(0x1000, end - a)
        data += dev.read(a, n); a += n
        print(f'read up to 0x{a:04x}', flush=True)
except IOError as e:
    print('stopped:', e)
open(out, 'wb').write(data)
print(f'saved 0x{start:04x}..0x{start+len(data):04x} ({len(data)} bytes) to {out}')
