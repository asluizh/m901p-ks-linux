# SPDX-License-Identifier: GPL-2.0-or-later
import pefile,re,sys
p=pefile.PE(sys.argv[1]);d=p.get_memory_mapped_image();B=p.OPTIONAL_HEADER.ImageBase
s=int(sys.argv[2],16)-B; n=int(sys.argv[3],16)
for m in re.finditer(rb'(?:[\x09\x0a\x0d\x20-\x7e]\x00){3,}',d[s:s+n]): print(hex(m.start()+s+B),repr(m.group().decode('utf-16le')))
