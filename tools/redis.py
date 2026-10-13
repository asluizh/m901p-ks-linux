# SPDX-License-Identifier: GPL-2.0-or-later
# small capstone helper for reversing OemDrv.exe
import sys, pefile, capstone, struct, re
P = pefile.PE(sys.argv[1]); BASE = P.OPTIONAL_HEADER.ImageBase
data = P.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32); md.detail = False
text = next(s for s in P.sections if s.Name.startswith(b'.text'))
TS, TE = BASE + text.VirtualAddress, BASE + text.VirtualAddress + text.Misc_VirtualSize
def va2off(va): return va - BASE
def find_str(s):
    return [m.start() + BASE for m in re.finditer(re.escape(s), data)]
def xrefs_imm(va):
    pat = struct.pack('<I', va)
    return [m.start() + BASE for m in re.finditer(re.escape(pat), data) if TS <= m.start()+BASE < TE]
def dis(va, n=40):
    out = []
    for i in md.disasm(data[va2off(va):va2off(va)+n*8], va):
        out.append(f'{i.address:08x}: {i.mnemonic} {i.op_str}')
        if len(out) >= n: break
    return out
if __name__ == '__main__':
    cmd = sys.argv[2]
    if cmd == 'str':
        for a in find_str(sys.argv[3].encode()):
            print(hex(a), [hex(x) for x in xrefs_imm(a)])
    elif cmd == 'xref':
        print([hex(x) for x in xrefs_imm(int(sys.argv[3], 16))])
    elif cmd == 'dis':
        print('\n'.join(dis(int(sys.argv[3], 16), int(sys.argv[4]) if len(sys.argv) > 4 else 40)))
