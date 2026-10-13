# M901P-KS Linux support — progress log

## Facts
- Installer is Inno Setup 5.3.3. Extracted via wine silent install into `work/wineprefix`; files copied to `work/driver/`.
  (`WINEPREFIX=work/wineprefix wine M901P-KS_Redragon_Setup.exe /VERYSILENT /DIR='C:\M901'`)
- Main app: `work/driver/OemDrv.exe` (generic Compx/OEM driver), config `work/driver/Cfg.ini`.
- Mouse: VID 0x25A7, PID 0xFA07 (2.4G receiver, currently plugged as "Compx 2.4G Wireless Receiver"), PID 0xFA08 (wired/other).
- Linux: receiver shows as /dev/hidraw0 (input0) and /dev/hidraw1 (input1), root-only perms.
- Cfg.ini: 16 keys (KM=32?), default mapping K1..K12 = '1'..'0','-'... (type 0x02 = keyboard), K13-15 = mouse buttons, K16 = DPI(?)
- Sensor 0x3335, 5 DPI levels 1000..16000.

## Steps
- [x] Extract driver
- [x] Reverse engineer HID protocol
- [x] Write CLI tool (`m901.py`) — untested on device yet
- [x] udev rule written (70-m901p-ks.rules) — needs user to install with sudo

## Protocol notes (from static RE of OemDrv.exe, see tools/redis.py)
- Lowerdev.dll fn ptrs in obj: +8 OpenHidDevice, +0xc SetFeature, +0x10 GetFeature, +0x14 GetProductString, +0x18 GetInputReport, +0x1c GetVersionNumber
- SendCommand @0x443a30: SetFeature(hDev, buf, 0x11); buf[0]=0x08 (report id), buf[1..15]=payload, buf[16]=checksum
- checksum @0x442ba0: 0x55 - sum(buf[0..15]) & 0xff  (sum includes report id 0x08)
- SendCMD @0x442bf0: payload[0]=nCmdID; if cmd==2: payload[3]=1, payload[4]=bData (offsets in payload incl? check)
- debug strings: WriteEEPROM @~0x4431a4, ReadEEPROM @~0x443460, handshake 'rand=..CheckOk' @0x442e3d
- Responses: input report 9 (ReadFile 0x11 bytes): resp[0]=cmd echo, resp[1]=status(0=ok), resp[5..]=data
- cmd 0x07 WriteEEPROM: payload 07 00 addrHi addrLo len data[len<=10]  (@0x443160)
- cmd 0x08 ReadEEPROM:  payload 08 00 addrHi addrLo len -> resp[5..] data (@0x443480)
- cmd 0x01 handshake: 01 00 00 00 04 r0 r1 r2 r3 ; device returns c0..c3 at resp[5..8]; key K @0x5d8fa4 (host verifies device)
- cmd 0x02 TellDrvStatus: 02 00 00 00 01 bData
- cmd 0x03 / 0x04: query, returns resp[5]
- EEPROM map (each 4-byte entry = b0,b1,b2,0x55-b0-b1-b2):
  - 0x0C + 4*i : DPI level i (dpiX code, dpiY code, flag)   (@0x4436f0)
  - 0x2C + 4*i : DPI color i (r,g,b?)                         (@0x4435c0)
  - 0x60 + 4*i : key matrix, i = 0..15 (button i+1)           (@0x443900)
  - 0x100 + 0x20*i : per-key data for type 5 (keyboard combo) entries; macros at table 0x5ce1e0[i]
  - Apply fn "Set Key" @0x40b780; key -> dword @0x40acc0; kbd data builder @0x40af50
- Key matrix dword codes (b0 = type), from fn @0x40acc0:
  - 00 00 00 disabled
  - 01 mm 00 mouse button: mm 01=L 02=R 04=M 08=Back 10=Forward
  - 04 32 02 / 04 32 03 : (internal ids 0x16/0x17, probably dbl-click / scroll? UNVERIFIED)
  - 04 p1 p0 : fire key (internal 0xa4, params from cfg e.g. 0x3A03 -> 04 3A 03) UNVERIFIED
  - 02 01 / 02 02 / 02 03 : DPI loop / DPI+ / DPI- (ids 0xaa,0xa8,0xa9)  (exact order UNVERIFIED)
  - 07, 08, 09 : other specials (ids 0xac, 0xa7, 0xb0)
  - 05 00 00 : keyboard/media -> data at EEPROM 0x100 + 0x20*matrixIdx
  - 06 00 rr : macro, data at table [0x300,0x480,...] (step 0x180) per matrix idx; rr repeat (0xff/0xfe/count)
- Keyboard data block: [n_events, ev*3..., chk=0x55-sum(all previous)], ev = (type, code, 0):
    0x80 mask 0 = modifier press (1 ctrl,2 shift,4 alt,8 win), 0x40 = modifier release
    0x81 hid 0 = key press, 0x41 hid 0 = key release (HID usage IDs)
    media: 0x82 lo hi / 0x42 lo hi (consumer usage), n=2
- Button -> matrix index (Cfg 4th value - 1): K1..K6 -> 0..5, K7->8, K8->9, K9->12, K10->13, K11->14, K12->15,
  K13(L)->7, K14(R)->6, K15(M)->10, K16(fire)->11
- Apply ends with WriteEEPROM(0x00, [x, 0x55-x]) and SendCMD(9) in some cases

## Next (as of 2026-10-13)
- Waiting for the user to install the udev rule (hidraw is root-only). Then:
  1. `./m901.py -v dump 0x60 64` to confirm the read protocol works
  2. `./m901.py backup work/factory.bin` BEFORE any write
  3. Check `show` against the factory defaults (side keys 1..0,-,= ; L,R,M ; fire) to confirm the button->matrix map
  4. Test `set` on a side button; verify with evtest / wev
  5. Open questions: does the firmware need handshake (cmd 1) or SendCMD(9) after writes? what are types 04/07/08/09?
- udev rule MUST be numbered <73 (uaccess is processed in 73-seat-late.rules); renamed to 70-m901p-ks.rules
- DEVICE TESTS (2026-10-13): udev ACL works. Commands answered via input report 9 (read() on hidraw1):
  - cmd3 -> resp[5]=01 ; cmd4 -> 02 04 ; handshake r=01 02 03 04 -> 08 07 0d 11 ; cmd2(1) -> echo 01
  - feature report 6 (GET) -> 06 00 02 64 64 64 21 (receiver status? battery 100?)
  - cmd 8 (EEPROM read) gets NO reply (any len) -> suspect mouse asleep / relay; testing with tools/wakeprobe.py while moving mouse
- READ WORKS when mouse awake (moved). Factory backup saved: work/factory.bin (0..0x1b00)
- FACTORY DUMP CONFIRMS button->matrix map and keydata format. Fire key = 04 14 03 (type 4: b1=interval?, b2=count).
  0x00: 01 54 (?) ; DPI 8 slots at 0x0c: 0b,17,2f,5f,bd,bd,bd,bd (x/y code) ; colors at 0x2c (r,g,b,chk)
- WRITE VERIFIED END-TO-END: `set 12 key:b` -> button 12 sends HID 0x05 (b), button 1 sends 0x1e; takes effect immediately, no commit cmd needed
  (tools/keywatch.py logs keyboard reports from hidraw1). Added `fire:INTERVAL,REPEAT` action.
- HOLD TEST in progress: button 11 set to key:shift+b (factory kp+), button 12 = kp- (factory). Restore 11 with: set 11 key:kp+
- HOLD TEST RESULT: single key held 1554 ms, combo shift+b held ~1754 ms -> firmware plays press events (0x8x) on button
  down, release events (0x4x) on button up, ~21 ms between events. Combos CAN be held. Encoder now releases key before mods.
- Fixed: parser handled "kp+" wrongly (split on '+'); trailing '+' now joins key name.
- `set` now pads the 32-byte keydata slot with 0xff. After restoring button 11 to kp+, full EEPROM == work/factory.bin (verified with cmp).
- NOTE: keydata addr = 0x100 + 0x20*matrixIdx (e.g. button 11 = idx 14 -> 0x2C0). Don't hand-compute wrong!
## Next: macro support (format @0x40b450 builder, 0x40b1e0 parser HdMacro_To_StMacro; macro slots 0x300 + 0x180*idx, matrix 06 00 rr)
- MACRO FORMAT (builder @0x40b450, parser @0x40b1e0), slot = 0x300 + 0x180*matrixIdx, max 0x180 bytes:
  [0]=name byte len, [1..30]=UTF-16LE name, [0x1f]=event count, events from 0x20, 5 bytes each:
  (0x80|type press / 0x40|type release, code, 0, delay_hi, delay_lo)  delay ms big-endian, after the event; driver min 3 (3 == "0")
  type 0 = modifier bits (1 LCtrl 2 LShift 4 LAlt 8 Win 10 RCtrl 20 RShift 40 RAlt), 1 = key (HID usage), 4 = mouse (1 L 2 R 4 M 8 back 10 fwd)
  then chk = 0x55 - sum(block[0..end]), then 3 zero bytes. Max events = 70.
  Matrix: 06 SLOT rr (SLOT = matrix idx, driver ORs idx<<8 @0x40b97a!) ; rr = N (cycle N times) / 0xff (mode1, prob. "until key released") / 0xfe (mode2, prob. "until any key pressed") UNVERIFIED which
- MACRO CLI implemented (m901.py macro). Device test: button 12 = macro 'h i 200 j' x2 (restore: set 12 key:kp-)
- MACRO TEST 1: user pressed button 12, keywatch (hidraw1 reports 1/5) logged NOTHING. Macro table addrs confirmed static. Re-testing with tools/allwatch.py (all reports, both hidraws)
- MACRO TEST 1 FAILED (nothing on either hidraw). Fix attempt: macro checksum must exclude name (driver checksums before inserting name, apply @0x40b8f7..0x40b9c2). Re-written button 12.
- MACRO TEST 2 (checksum excl. name) FAILED too.
- Fix attempt 3: macro matrix entry byte1 = slot index (06 idx rr). Checksum still excl. name.
- MACRO WORKS (test 3): button 12 = 'h i 200 j' x2 -> hijhij, 20 ms steps, 197 ms pause, repeat 2 OK. Fix was matrix byte1 = slot.
- Next: verify loop modes 0xff / 0xfe (button 11 = --while-held, button 12 = --until-key), then restore 11->kp+, 12->kp-
- LOOP TEST: 0xff is NOT "while held": button 11 (a, 0xff) looped forever after release (268 a's / 45 s), user had to power the
  mouse off. No click reports seen during loop. So 0xff = probably "until any key pressed" (but clicks didn't stop it?);
  0xfe = probably "until released" (UNTESTED). (restored with a retry loop once the mouse came back).
  SAFETY: future loop tests must use a harmless key (f24) and get user consent.
- Restored: buttons 11/12 + macro slots 14/15 -> EEPROM identical to factory.bin again.
- Tool: --while-held/--until-key replaced by experimental --loop ff|fe; macro writes pad slot to 0x180 with ff.
- FE TEST: button 12 = macro f24 loop 0xfe (restore: set 12 key:kp- ; restore slot 15 from factory 0x1980..0x1b00)
- FE TEST RESULT: 0xfe = LOOP WHILE HELD (13 f24 taps over 2 s hold, stopped on release). Tool: --while-held = 0xfe,
  --until-key = 0xff (with warning). Button 12 + slot 15 restored, EEPROM identical to factory again.
- SHIPPED initial state: git repo initialized, first commit on main (local only, no remote).
