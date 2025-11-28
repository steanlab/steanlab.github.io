** Lenovo X220 v1.45 Modified Bios (no whitelist only) **

- Whitelist removal only
- Re-signed with custom key to get rid of 5 beeps on boot

** Lenovo X220 v1.45 Modified Bios (full-blown) **

- Whitelist removal
- Unlocked AES-NI on "no-encryption" machines
- Unlocked hidden advanced menu
- Unlocked memory speed (supports DDR3 1600 and 1866)
- Disabled package c-state lock at MSR 0xE2 (for Hackintosh)
- Re-signed with custom key to get rid of 5 beeps on boot

Be careful with advanced menu. Changing some options may render your laptop unbootable!
More memory speed means more heat, 1866 MHz memory speed may increase your laptop temperature up to 5°C.

First flash the original v1.45 bios from "Lenovo X220 v1.45 Original Bios" folder, reboot and run flash.bat from one of the modified BIOS folder as an administrator.

These modifications were made by camiloml, BDMaster, Serg008, Oleh/Rambler and others. I'm (ValdikSS) only created hash recomputation and re-signing script and keep backporting all modifications from older to newer BIOS versions.
