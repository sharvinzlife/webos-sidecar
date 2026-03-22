# LG Developer Mode quick guide

This repo follows the official LG flow exactly, but says it in the order most people actually need:

1. On the TV remote, press `Home`.
2. Open `LG Content Store`.
3. Search for `Developer Mode`.
4. Install and launch that app.
5. Sign in with your LG Developer account.
6. Turn `Dev Mode Status` on.
7. Let the TV reboot.
8. Open `Developer Mode` again.
9. Press `Key Server`.
10. Look at the bottom-left of the screen for the 6-character passphrase.
11. In this dashboard, use the TV IP, port `9922`, and user `prisoner`.
12. Leave the password empty and enter the passphrase when prompted.

Important:

- LG Key Server codes are case-sensitive.
- `webOS Sidecar` now normalizes them to uppercase before saving them into the LG CLI device config.

If sideloading suddenly stops working:

- make sure the TV and your computer are still on the same LAN
- confirm `Dev Mode Status` is still on
- press `EXTEND` before the remaining session hits zero
- regenerate the SSH key if you changed networks or the TV reset developer mode

Packaging reminder:

- LG webOS TV: `.ipk`
- Samsung/Tizen: `.wgt`
