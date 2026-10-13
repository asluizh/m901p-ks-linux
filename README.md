# Redragon M901P-KS on Linux

The mouse already works as a normal mouse and keyboard on Linux. `m901.py` reprograms its on-board
button mapping, macros, profiles and polling rate. They are stored in the mouse, so they keep working without any software running,
on any computer.

Supported device: Redragon M901P-KS via its 2.4G receiver (USB `25a7:fa07`). The wired ID `25a7:fa08` is
detected too but untested.

Single Python 3 file, standard library only.

## Setup (once)

    sudo cp 70-m901p-ks.rules /etc/udev/rules.d/
    sudo udevadm control --reload && sudo udevadm trigger --action=add --subsystem-match=hidraw

The rule must sort before `73-seat-late.rules`, which is why it is numbered 70. Otherwise the `uaccess` tag
is never applied.

**Back up your current configuration before changing anything:**

    ./m901.py backup m901-factory.bin

This saves the whole 16 KB memory, including both profiles. It takes about 10 seconds.

## Buttons

| Number | Button |
|---|---|
| 1-12 | Side grid, numbered as in the Windows app (factory: `1`…`0`, numpad `+`, numpad `-`) |
| 13 / `left` | Left button |
| 14 / `right` | Right button |
| 15 / `middle` | Middle button |
| 16 / `fire` | Fire button |

## Remapping

    ./m901.py show                       # current mapping, including macros
    ./m901.py set 1 key:ctrl+c           # key or combo (can be held down)
    ./m901.py set 2 key:f13
    ./m901.py set 3 media:volup          # media keys
    ./m901.py set 4 back                 # mouse buttons: left right middle back forward
    ./m901.py set 5 dpi-up               # dpi-up dpi-down dpi-loop (untested)
    ./m901.py set 16 fire:20,3           # fire key: interval, repeat (factory setting)
    ./m901.py set 12 disable
    ./m901.py keys                       # list every key/action name

## Profiles and polling rate

The mouse has **two profiles**. The button on the underside switches between them, and the scroll-wheel LED
blinks to confirm. Each profile has its own button mapping and polling rate. Factory settings: profile A at
1000 Hz, profile B at 125 Hz. There is no software command to switch profiles; only the button does it.

    ./m901.py profile                    # which profile is active, and both rates
    ./m901.py show -p B                  # mapping of profile B, even while A is active
    ./m901.py set 1 key:f13 -p B         # change a button in profile B
    ./m901.py rate                       # polling rate of the active profile
    ./m901.py rate 500                   # 125, 250, 500 or 1000 Hz; applies immediately

- Without `-p`, `show`, `set` and `macro` act on the active profile.
- `rate` only works on the active profile, because the mouse ignores rate changes written to the stored one.
  Switch to the profile first.

## Macros

    ./m901.py macro 5 'ctrl+a 50 ctrl+c'                 # select all, wait 50 ms, copy
    ./m901.py macro 6 --while-held mouse:left 30         # autoclicker while the button is held
    ./m901.py macro 7 '+shift h -shift ello' --repeat 3  # press/release separately
    ./m901.py macro 8 -f script.txt --name build         # read the script from a file

Script tokens, separated by spaces or commas:

| Token | Meaning |
|---|---|
| `a` | Tap a key (press, then release) |
| `ctrl+shift+t` | Tap a combo |
| `+a` / `-a` | Press only / release only |
| `mouse:left` | Mouse button (also `right`, `middle`, `back`, `forward`) |
| `150` or `150ms` | Pause after the previous step |

- Each step waits 20 ms by default (change with `--delay`).
- Up to 70 steps.
- Right-hand modifiers (`rctrl`, `rshift`, `ralt`) work in macros.

Macros are stored in 16 slots shared by both profiles. By default, a button uses the slot with its own number. If
that slot is already used by the same button in the other profile, the tool refuses rather than overwrite it.
Pick another slot with `--slot N`, for example `./m901.py macro 12 -p A --slot 3 'f24'`.

Playback modes:

| Option | Behaviour |
|---|---|
| `--repeat N` | Play N times (1-253, default 1) |
| `--while-held` | Loop while the button is held, stop on release |
| `--until-key` | **Caution:** keeps looping after release. In testing only switching the mouse off stopped it. |

## Restore

    ./m901.py restore m901-factory.bin

## Troubleshooting

- **"no response to command 0x08":** the mouse is asleep. Move it and run the command again.
- **"permission denied":** the udev rule isn't installed or applied (see Setup).
- **Debugging:** `-v` prints the raw HID traffic. `dump ADDR LEN`, `write ADDR BYTES…` and `raw BYTES…` give
  low-level access.

## Not supported yet

DPI levels and lighting. Their data is partly located in the mouse's memory; see the protocol notes.

## How it works

The protocol was reverse-engineered from the vendor's Windows app (`OemDrv.exe`) and verified on the mouse.
See [PROGRESS.md](PROGRESS.md) for the protocol, the EEPROM map, the driver code addresses and the test log.
The helper scripts used are in `tools/`.

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
