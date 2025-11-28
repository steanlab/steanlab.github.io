data.vbt -> VBT (Video BIOS Table) from Thinkpad X220 FRU 04W3286 (i5 2520M) via sudo cat /sys/kernel/debug/dri/0/i915_vbt > data.vbt

edid_lvds_TLB1.bin -> EDID (Extended Display Identification Data) from Thinkpad X220 13,3" LP125WH2(TL)(B1) via cp /sys/devices/pci0000:00/0000:00:02.0/drm/card0/card0-LVDS-1/edid ~/edid_lvds_TLB1.bin

edid_lvds_SLT1_IPS.bin -> EDID (Extended Display Identification Data) from Thinkpad X220 13,3" LP125WH2(SL)(T1) via cp /sys/devices/pci0000:00/0000:00:02.0/drm/card0/card0-LVDS-1/edid ~/edid_lvds_SLT1_IPS.bin
