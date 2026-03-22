from __future__ import annotations

from typing import Any


def build_troubleshooting(stage: str, output: str, file_suffix: str | None = None) -> list[dict[str, Any]]:
    lowered = output.lower()
    tips: list[dict[str, Any]] = []

    if file_suffix == ".wgt":
        tips.append(
            {
                "title": "Wrong package type for LG webOS TV",
                "cause": "LG webOS TV sideloading uses .ipk packages. .wgt is usually for Samsung/Tizen, not LG TVs.",
                "steps": [
                    "Download the LG/webOS release asset that ends in .ipk.",
                    "If the repo only ships source code, package the webOS app into an .ipk first.",
                    "For Moonfin-style projects, use the Smart TV release asset, not the umbrella repo zip.",
                ],
            }
        )

    if "no ipk assets" in lowered or "no .ipk assets" in lowered:
        tips.append(
            {
                "title": "The repo does not publish an LG package",
                "cause": "The GitHub release you pointed at does not contain a ready-to-install .ipk file.",
                "steps": [
                    "Check the repo releases for a webOS or LG-specific asset.",
                    "If the repo is only source code, build/package it first.",
                    "Use a direct .ipk release asset URL when possible.",
                ],
            }
        )

    if any(token in lowered for token in ["permission denied", "auth fail", "authentication", "publickey"]):
        tips.append(
            {
                "title": "SSH key or passphrase mismatch",
                "cause": "The TV did not accept the key exchange. This usually means Key Server is off, the 6-character passphrase was mistyped, or Developer Mode expired.",
                "steps": [
                    "Open the Developer Mode app on the TV again.",
                    "Confirm Dev Mode Status is still ON and tap Key Server right before retrying.",
                    "Enter the exact 6-character passphrase again, including case.",
                    "Keep the TV on the Developer Mode screen while the dashboard runs the link step.",
                    "If the remaining session expired, turn Developer Mode back on and extend the session.",
                ],
            }
        )

    if any(
        token in lowered
        for token in [
            "cannot parse privatekey",
            "unable to parse private key",
            "bad passphrase",
            "incorrect passphrase",
            "malformed openssh private key",
        ]
    ):
        tips.append(
            {
                "title": "The Key Server code did not match the downloaded key",
                "cause": "The TV key file was downloaded, but the saved 6-character passphrase does not decrypt it. That usually means the code was mistyped, expired, or copied from an older Key Server screen.",
                "steps": [
                    "Open Developer Mode on the TV again and tap Key Server to get the current 6-character code.",
                    "Type the code exactly as shown right now on the TV, then run Link with Key Server again.",
                    "Do not reuse an older code after reopening Key Server or rebooting the TV.",
                    "If it repeats, save the TV again in Step 1 and retry Step 2 immediately while Key Server stays open.",
                ],
            }
        )

    if "private key file or password does not exist" in lowered:
        tips.append(
            {
                "title": "The TV was not linked successfully yet",
                "cause": "Install reached the CLI, but the LG device entry still has no usable SSH credentials. On webOS TV that usually means the saved device is missing the SSH key name, the saved Key Server passphrase, or both.",
                "steps": [
                    "Go back to Step 2 and finish Link with Key Server without errors.",
                    "Keep the TV on the Developer Mode screen with Key Server visible while linking.",
                    "After Step 2 succeeds, confirm the saved TV shows both an SSH key and a passphrase.",
                    "If Step 2 still fails, remove the TV entry, save it again, and retry the key link before installing.",
                    "Only run Install to TV after Step 2 shows a successful key exchange and connection check.",
                ],
            }
        )

    if "all configured authentication methods failed" in lowered or "ssh exec failure" in lowered:
        tips.append(
            {
                "title": "The TV rejected the saved SSH credentials",
                "cause": "The dashboard reached the TV, but the saved key was not accepted. This usually means the Key Server step did not finish cleanly or the device entry is still holding stale auth details.",
                "steps": [
                    "On the TV, open Developer Mode and tap Key Server again.",
                    "Save the TV entry again in Step 1, then retry Step 2 immediately.",
                    "If it still fails, remove the TV entry and add it again with the same IP, port 9922, and user prisoner.",
                    "Make sure the TV is still on the Developer Mode screen while you click Link with Key Server.",
                ],
            }
        )

    if any(token in lowered for token in ["timed out", "timeout", "refused", "econnrefused", "no route", "network is unreachable"]):
        tips.append(
            {
                "title": "The TV is not reachable on your network",
                "cause": "Your computer could not reach the TV over the developer SSH port.",
                "steps": [
                    "Make sure the TV and computer are on the same LAN.",
                    "Double-check the TV IP address and use port 9922.",
                    "Open the Developer Mode app and verify Dev Mode Status is ON.",
                    "If your router isolates devices, disable client isolation or try a different network.",
                ],
            }
        )

    if any(token in lowered for token in ["device not found", "unknown device", "not in device list"]):
        tips.append(
            {
                "title": "The target TV was never added",
                "cause": "The CLI does not know about the device alias you selected.",
                "steps": [
                    "Add the TV in the Device panel first.",
                    "Use the TV's current IP address, port 9922, and username prisoner.",
                    "Mark it as default if you only use one TV.",
                ],
            }
        )

    if "appinfo.json" in lowered and stage == "package":
        tips.append(
            {
                "title": "The uploaded zip is not a buildable webOS app",
                "cause": "Packaging needs a folder containing a valid appinfo.json file.",
                "steps": [
                    "Upload the final .ipk if the project already publishes one.",
                    "If you upload source, make sure the archive contains the built webOS app folder.",
                    "For monorepos, zip only the webOS app directory instead of the whole repository.",
                ],
            }
        )

    if "developer mode" in lowered or "session" in lowered:
        tips.append(
            {
                "title": "Developer Mode probably expired",
                "cause": "LG removes developer-installed apps when Developer Mode turns off or the session runs out.",
                "steps": [
                    "Open the Developer Mode app.",
                    "Turn Dev Mode Status back on if needed.",
                    "Press EXTEND before the remaining session reaches zero.",
                    "Re-run the key setup if the TV was reset or rebooted out of developer mode.",
                ],
            }
        )

    if not tips and output:
        tips.append(
            {
                "title": "Read the raw CLI output",
                "cause": "The wrapper could not match this error to a known shortcut fix.",
                "steps": [
                    "Look at the command output in the activity panel.",
                    "Retry the step after confirming Developer Mode, Key Server, IP address, and .ipk package type.",
                    "If the same output keeps repeating, capture that exact message before changing anything else.",
                ],
            }
        )

    return tips
