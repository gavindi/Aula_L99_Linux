# aula_l99_hacky

Linux tool for the AULA L99's vendor HID channel (`0C45:800A` wired, `05AC:024F` 2.4G
dongle). This only covers the **keyboard-side HID protocol** — the touchscreen is a
separate `EEEF:268A` USB-serial device, already documented in
[Salamor/aula-l99-open-widgets](https://github.com/Salamor/aula-l99-open-widgets).

## Status

- Session handshake (init/query) and the RTC-set command: confirmed, copied from
  [Simon-Martens/F75_Initializer](https://github.com/Simon-Martens/F75_Initializer),
  which reverse-engineered the *exact same VID/PID* (the L99's keyboard chip is
  identical to the AULA F75 MAX).
- RGB/lighting/macro commands: **not yet known for this VID/PID**. `--send-hex`
  exists to test candidate packets you pull from your own capture.

## Usage

```bash
# find the hidraw device (needs the keyboard plugged in; run as root or with a udev rule)
sudo python3 -m aula_l99_hacky.cli --list

# confirm the handshake works at all on real hardware
sudo python3 -m aula_l99_hacky.cli --handshake --debug

# sanity check: set the keyboard's RTC (dongle path only for now)
sudo python3 -m aula_l99_hacky.cli --rtc --debug

# test a packet captured from the official Windows driver (Wireshark + USBPcap)
sudo python3 -m aula_l99_hacky.cli --send-hex "06 84 00 00 01 00 80 00 00 ..."
```

## Getting the RGB commands

1. Windows VM/machine with the keyboard attached, `DeviceDriver.exe` installed
   (from `Windows/AULA L99/` in this repo), Wireshark + USBPcap.
2. Capture while changing **one** setting at a time in the app (color, then
   brightness, then speed, then effect) so each capture isolates one field.
3. Filter to `usb.device_address == <N>` for the `0C45:800A` device, find the
   `SET_REPORT`/`GET_REPORT` control transfers, copy the hex payload.
4. Feed each candidate into `--send-hex` here to confirm it reproduces the
   effect without the vendor app running, then fold the confirmed layout back
   into `protocol.py`.

See `/home/ggraham/Projects/Aula_L99/Windows/AULA L99/PLAN.md` for the full
research writeup and links to prior art (F75_Initializer, aula-rgb-controller,
aula-l99-open-widgets, OpenRGB AULA MRs).
