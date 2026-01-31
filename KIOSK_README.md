# OTP Kiosk Lockdown System

Turn a Raspberry Pi 5 (or Ubuntu VM) into a dedicated secure messaging terminal.

## What's Included

| File | Purpose |
|------|---------|
| `setup_kiosk_vm_test.sh` | **Start here** - Lighter setup for testing in a VM |
| `setup_kiosk.sh` | Full production lockdown for Pi 5 |
| `kiosk_launcher_standalone.py` | Run the launcher without system changes |

## Quick Start (VM Testing)

```bash
# 1. Put all your OTP files in one folder
mkdir ~/otp_test
cp otp_client.py otp_relay_server.py otp_generator.py otp_cipher.txt ~/otp_test/
cp otp_kiosk/* ~/otp_test/

# 2. Run the setup
cd ~/otp_test
sudo ./setup_kiosk_vm_test.sh

# 3. Reboot into kiosk mode
sudo reboot
```

After reboot, the system will auto-login and show the kiosk launcher.

**To exit**: Press Escape 3 times quickly (VM test mode only)

**To remove**: 
```bash
sudo /root/remove_kiosk_test.sh
sudo reboot
```

## Standalone Launcher (No System Changes)

Just want the kiosk interface without modifying the system?

```bash
# Put all files in the same directory, then:
python3 kiosk_launcher_standalone.py
```

Press Escape 3x to exit. Edit `PRODUCTION_MODE = True` in the file to disable the escape.

## Production Lockdown (Pi 5)

⚠️ **Test in a VM first!** This makes significant system changes.

```bash
# Copy all OTP files to the setup directory
sudo ./setup_kiosk.sh
sudo reboot
```

### What the production lockdown does:
- Creates a dedicated `otpuser` account
- Configures auto-login to minimal Openbox session
- Blocks Ctrl+Alt+F1-F12 terminal switching
- Disables screen blanking
- Removes window decorations
- Restricts shell access
- Auto-restarts the launcher if closed

### Recovery

If you need to regain access:

1. **From recovery mode**: Boot with recovery option, run `/root/disable_kiosk.sh`
2. **With keyboard**: If you have physical access, hold Shift during boot for GRUB menu
3. **SSH**: If SSH is enabled, login remotely as your admin user

## Architecture

```
┌─────────────────────────────────────────────┐
│              Kiosk Launcher                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ Client   │ │ Server   │ │Generator │    │
│  └──────────┘ └──────────┘ └──────────┘    │
└─────────────────────────────────────────────┘
         │              │            │
         ▼              ▼            ▼
    otp_client.py  otp_relay_   otp_generator.py
                   server.py         │
         │              │            ▼
         │              │      /dev/hwrng
         ▼              ▼      (Pi 5 TRNG)
    otp_cipher.txt ◄────┴────────────┘
    used_pages.txt
```

## Security Considerations

1. **OTP file distribution**: The `otp_cipher.txt` must be copied securely to all parties BEFORE using the system (USB stick, in person)

2. **Physical security**: A determined attacker with physical access could still boot from USB. Consider full disk encryption for sensitive deployments.

3. **Network**: The relay server uses ngrok for NAT traversal. For maximum security, use a direct connection or VPN instead.
