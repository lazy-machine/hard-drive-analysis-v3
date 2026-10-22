# Hardware Report: archmachine

_Generated 2026-10-21 21:23 -03 by hwspec.sh_

## System

| Property | Value |
|---|---|
| Manufacturer | ASUS |
| Model | System Product Name System Version |
| Chassis type | desktop 🖥️ |
| OS | Arch Linux |
| Kernel | 7.2.11-arch1-1 (x86_64) |
| Uptime | up 1 day, 14 hours, 19 minutes |

## Motherboard & Firmware

| Property | Value |
|---|---|
| Board | ASUSTeK COMPUTER INC. TUF GAMING B550M-PLUS Rev X.0x |
| BIOS vendor | American Megatrends Inc. |
| BIOS version | 3636 |
| BIOS date | 01/04/2026 |
| Boot mode | UEFI |

## CPU

| Property | Value |
|---|---|
| Model | AMD Ryzen 7 5700X 8-Core Processor |
| Architecture | x86_64 |
| Sockets | 1 |
| Cores / socket | 8 |
| Threads / core | 2 |
| Logical CPUs | 16 |
| Max clock | 4666 MHz |
| L1d / L1i cache | 256 KiB (8 instances) / 256 KiB (8 instances) |
| L2 cache | 4 MiB (8 instances) |
| L3 cache | 32 MiB (1 instance) |
| Virtualization | AMD-V |

## Memory

| Property | Value |
|---|---|
| Total RAM | 31.2 GiB |
| Swap | 36.0 GiB |
| Max capacity | 128 GiB |
| Slots | 4 |

### Installed modules

| Slot | Size | Type | Speed | Manufacturer | Part number |
|---|---|---|---|---|---|
| DIMM_A2 | 16 GiB | DDR4 | 3200 MT/s | Micron | DDR4 16GB 3200MHz |
| DIMM_B2 | 16 GiB | DDR4 | 3200 MT/s | Micron | DDR4 16GB 3200MHz |

## Storage

| Device | Model | Size | Kind | Interface |
|---|---|---|---|---|
| /dev/sda | SAMSUNG HD502IJ | 465.8G | HDD | sata |
| /dev/sdb | ST500LM012 HN-M500MBB | 465.8G | HDD | sata |
| /dev/nvme0n1 | WDC WDS480G2G0C-00AJM0 | 447.1G | NVMe SSD | nvme |

### Filesystems

```
Filesystem     Type  Size  Used Avail Use% Mounted on
/dev/nvme0n1p3 ext4  407G  200G  187G  52% /
/dev/nvme0n1p1 vfat 1022M  265M  758M  26% /boot
/dev/sdb       ext4  458G  134G  301G  31% /HDMedia
/dev/sda       ext4  458G   82G  353G  19% /home/lazy/HDDownloads
```

## Graphics

- Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7700 XT / 7800 XT] (rev c8)

### AMD (amdgpu driver)

| Card | Model | VRAM | VBIOS | Driver |
|---|---|---|---|---|
| card1 | Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7700 XT / 7800 XT] (rev c8) | 16.0 GiB | 113-EXT104128-100 | amdgpu |

## Network Interfaces

| Interface | Kind | Hardware | Driver | Link speed | State |
|---|---|---|---|---|---|
| enp6s0 | Ethernet | Realtek Semiconductor Co., Ltd. RTL8125 2.5GbE Controller (rev 05) | r8169 | 1000 Mb/s | up |

## Temperatures & Fans

```
zenpower-pci-00c3
Adapter: PCI adapter
SVI2_Core:     1.01 V  
SVI2_SoC:    994.00 mV 
Tdie:         +35.6 C  (high = +95.0 C)
Tctl:         +35.6 C  
Tccd1:        +36.8 C  
SVI2_P_Core:   7.25 W  
SVI2_P_SoC:    4.68 W  
SVI2_C_Core:   7.25 A  
SVI2_C_SoC:    4.71 A  

nvme-pci-0100
Adapter: PCI adapter
Composite:    +34.9 C  (low  =  -5.2 C, high = +79.8 C)
                       (crit = +84.8 C)

nct6798-isa-0290
Adapter: ISA adapter
in0:                      504.00 mV (min =  +0.00 V, max =  +1.74 V)
in1:                      1000.00 mV (min =  +0.00 V, max =  +0.00 V)  ALARM
in2:                        3.38 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
in3:                        3.30 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
in4:                        1.01 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
in5:                      848.00 mV (min =  +0.00 V, max =  +0.00 V)
in6:                      264.00 mV (min =  +0.00 V, max =  +0.00 V)  ALARM
in7:                        3.38 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
in8:                        3.31 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
in9:                        1.79 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
in10:                     848.00 mV (min =  +0.00 V, max =  +0.00 V)  ALARM
in11:                     848.00 mV (min =  +0.00 V, max =  +0.00 V)  ALARM
in12:                       1.03 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
in13:                     992.00 mV (min =  +0.00 V, max =  +0.00 V)  ALARM
in14:                       1.01 V  (min =  +0.00 V, max =  +0.00 V)  ALARM
fan1:                      514 RPM  (min =    0 RPM)
fan2:                      721 RPM  (min =    0 RPM)
fan3:                      587 RPM  (min =    0 RPM)
fan7:                        0 RPM  (min =    0 RPM)
SYSTIN:                    +34.0 C  (high = +80.0 C, hyst = +75.0 C)
                                    (crit = +125.0 C)  sensor = thermistor
CPUTIN:                    +33.0 C  (high = +80.0 C, hyst = +75.0 C)
                                    (crit = +125.0 C)  sensor = thermistor
AUXTIN0:                   +83.0 C  (high = +80.0 C, hyst = +75.0 C)  ALARM
                                    (crit = +125.0 C)  sensor = thermistor
AUXTIN1:                   +34.0 C  (high = +80.0 C, hyst = +75.0 C)
                                    (crit = +100.0 C)  sensor = thermistor
AUXTIN2:                   +34.0 C  (high = +80.0 C, hyst = +75.0 C)
                                    (crit = +100.0 C)  sensor = thermistor
AUXTIN3:                   +25.0 C  (high = +80.0 C, hyst = +75.0 C)
                                    (crit = +100.0 C)  sensor = thermistor
AUXTIN4:                   +34.0 C  (high = +80.0 C, hyst = +75.0 C)
                                    (crit = +100.0 C)
PECI Agent 0 Calibration:  +33.0 C  (high = +80.0 C, hyst = +75.0 C)
PCH_CHIP_CPU_MAX_TEMP:      +0.0 C  
PCH_CHIP_TEMP:              +0.0 C  
PCH_CPU_TEMP:               +0.0 C  
PCH_MCH_TEMP:               +0.0 C  
TSI0_TEMP:                 +35.5 C  
pwm1:                          44%  (mode = pwm)
pwm2:                          44%  (mode = pwm)
pwm3:                          44%  (mode = pwm)
pwm7:                         128%  (mode = pwm)
intrusion0:               ALARM
intrusion1:               ALARM
beep_enable:              disabled

r8169_0_600:00-mdio-0
Adapter: MDIO adapter
temp1:        +44.0 C  (high = +120.0 C)

amdgpu-pci-0900
Adapter: PCI adapter
vddgfx:      307.00 mV 
fan1:           0 RPM  (min =    0 RPM, max = 3300 RPM)
edge:         +38.0 C  (crit = +100.0 C, hyst = -273.1 C)
                       (emerg = +105.0 C)
junction:     +45.0 C  (crit = +110.0 C, hyst = -273.1 C)
                       (emerg = +115.0 C)
mem:          +40.0 C  (crit = +108.0 C, hyst = -273.1 C)
                       (emerg = +113.0 C)
PPT:          12.00 W  (cap = 242.00 W)
pwm1:              0%
sclk:          15 MHz 
mclk:          96 MHz 

```

## Full Device Listings

<details><summary>PCI devices (lspci)</summary>

```
00:00.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse Root Complex
00:00.2 IOMMU: Advanced Micro Devices, Inc. [AMD] Starship/Matisse IOMMU
00:01.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Host Bridge
00:01.1 PCI bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse GPP Bridge
00:01.2 PCI bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse GPP Bridge
00:02.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Host Bridge
00:03.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Host Bridge
00:03.1 PCI bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse GPP Bridge
00:04.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Host Bridge
00:05.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Host Bridge
00:07.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Host Bridge
00:07.1 PCI bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse Internal PCIe GPP Bridge 0 to bus[E:B]
00:08.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Host Bridge
00:08.1 PCI bridge: Advanced Micro Devices, Inc. [AMD] Starship/Matisse Internal PCIe GPP Bridge 0 to bus[E:B]
00:14.0 SMBus: Advanced Micro Devices, Inc. [AMD] FCH SMBus Controller (rev 61)
00:14.3 ISA bridge: Advanced Micro Devices, Inc. [AMD] FCH LPC Bridge (rev 51)
00:18.0 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 0
00:18.1 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 1
00:18.2 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 2
00:18.3 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 3
00:18.4 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 4
00:18.5 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 5
00:18.6 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 6
00:18.7 Host bridge: Advanced Micro Devices, Inc. [AMD] Matisse/Vermeer Data Fabric: Device 18h; Function 7
01:00.0 Non-Volatile memory controller: Sandisk Corp WD Green SN350 240GB (DRAM-less) / SN560E NVMe SSD (rev 01)
02:00.0 USB controller: Advanced Micro Devices, Inc. [AMD] 500 Series Chipset USB 3.1 XHCI Controller
02:00.1 SATA controller: Advanced Micro Devices, Inc. [AMD] 500 Series Chipset SATA Controller
02:00.2 PCI bridge: Advanced Micro Devices, Inc. [AMD] 500 Series Chipset Switch Upstream Port
03:00.0 PCI bridge: Advanced Micro Devices, Inc. [AMD] 500 Series Chipset Switch Downstream Port
03:08.0 PCI bridge: Advanced Micro Devices, Inc. [AMD] 500 Series Chipset Switch Downstream Port
03:09.0 PCI bridge: Advanced Micro Devices, Inc. [AMD] 500 Series Chipset Switch Downstream Port
06:00.0 Ethernet controller: Realtek Semiconductor Co., Ltd. RTL8125 2.5GbE Controller (rev 05)
07:00.0 PCI bridge: Advanced Micro Devices, Inc. [AMD/ATI] Navi 10 XL Upstream Port of PCI Express Switch (rev 11)
08:00.0 PCI bridge: Advanced Micro Devices, Inc. [AMD/ATI] Navi 10 XL Downstream Port of PCI Express Switch (rev 11)
09:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7700 XT / 7800 XT] (rev c8)
09:00.1 Audio device: Advanced Micro Devices, Inc. [AMD/ATI] Navi 31 HDMI/DP Audio
0a:00.0 Non-Essential Instrumentation [1300]: Advanced Micro Devices, Inc. [AMD] Starship/Matisse PCIe Dummy Function
0b:00.0 Non-Essential Instrumentation [1300]: Advanced Micro Devices, Inc. [AMD] Starship/Matisse Reserved SPP
0b:00.1 Encryption controller: Advanced Micro Devices, Inc. [AMD] Starship/Matisse Cryptographic Coprocessor PSPCPP
0b:00.3 USB controller: Advanced Micro Devices, Inc. [AMD] Matisse USB 3.0 Host Controller
```

</details>
<details><summary>USB devices (lsusb)</summary>

```
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 001 Device 002: ID 0b05:1939 ASUSTek Computer, Inc. AURA LED Controller
Bus 001 Device 003: ID 05e3:0608 Genesys Logic, Inc. Hub
Bus 001 Device 006: ID 3434:0530 Keychron Keychron C3 Pro 8K
Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 003 Device 002: ID 1d57:fa60 Xenta 2.4G Wireless Device
Bus 003 Device 003: ID 3142:0068 MV-SILICON fifine Microphone
Bus 003 Device 004: ID 3302:43e8 TTGK Technology TE-C
Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
```

</details>
<details><summary>CPU flags</summary>

```
fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 
ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm constant_tsc rep_good nopl xtopology nonstop_tsc 
cpuid extd_apicid aperfmperf rapl pni pclmulqdq monitor ssse3 fma cx16 sse4_1 sse4_2 x2apic movbe 
popcnt aes xsave avx f16c rdrand lahf_lm cmp_legacy svm extapic cr8_legacy abm sse4a misalignsse 
3dnowprefetch osvw ibs skinit wdt tce topoext perfctr_core perfctr_nb bpext perfctr_llc mwaitx cpb 
cat_l3 cdp_l3 hw_pstate ssbd mba ibrs ibpb stibp vmmcall fsgsbase bmi1 avx2 smep bmi2 erms invpcid 
cqm rdt_a rdseed adx smap clflushopt clwb sha_ni xsaveopt xsavec xgetbv1 xsaves cqm_llc 
cqm_occup_llc cqm_mbm_total cqm_mbm_local user_shstk clzero irperf xsaveerptr rdpru wbnoinvd arat 
npt lbrv svm_lock nrip_save tsc_scale vmcb_clean flushbyasid decodeassists pausefilter pfthreshold 
avic v_vmsave_vmload vgif v_spec_ctrl umip pku ospke vaes vpclmulqdq rdpid overflow_recov succor 
smca fsrm debug_swap
```

</details>
