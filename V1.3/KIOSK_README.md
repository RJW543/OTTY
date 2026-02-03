# OTP Secure Communications System

Turn a Raspberry Pi 5 (or Ubuntu VM) into a dedicated secure messaging and voice call terminal.

## Features

| Feature | Encryption | Description |
|---------|------------|-------------|
| Contacts Hub | - | Central contact management and communication launcher |
| Text Messaging | One-Time Pad (XOR) | Information-theoretically secure text messages |
| Voice Calls | AES-256-GCM | Encrypted real-time voice with group support |
| OTP Generation | Hardware RNG (Pi 5) | True random key generation from `/dev/hwrng` |

## What's Included

| File | Purpose |
|------|---------|
| `otp_contacts.py` | **NEW** - Central contact manager and communication hub |
| `otp_client.py` | OTP-encrypted text messaging client |
| `otp_voice_client.py` | AES-encrypted voice calls (1-on-1 and group) |
| `otp_relay_server_voice.py` | Relay server with voice room support |
| `otp_relay_server.py` | Basic relay server (text only) |
| `otp_generator.py` | Hardware RNG-based OTP key generator |
| `kiosk_launcher_standalone.py` | Kiosk launcher with all apps |
| `setup_kiosk_vm_test.sh` | VM test setup script |
| `setup_kiosk.sh` | Full production lockdown for Pi 5 |

## Quick Start

### 1. Install Dependencies

```bash
# Core dependencies
sudo apt-get install python3 python3-tk python3-pip portaudio19-dev

# Python packages
pip install pyngrok cryptography pyaudio --break-system-packages
```

### 2. Initial Device Setup (Admin)

On first launch of the Contacts app, you'll be prompted to enter the device's unique ID:

```bash
python3 otp_contacts.py
```

- Enter an 11-character ID (a-z, 0-9 only)
- Example: `abc12def345`
- This ID uniquely identifies the device on the network
- This step is done by the admin before giving the device to the user

### 3. Run the Applications

```bash
# Run the kiosk launcher (recommended - includes all apps)
python3 kiosk_launcher_standalone.py

# Or run the Contacts app directly
python3 otp_contacts.py

# Or run individual apps:
python3 otp_relay_server_voice.py  # Start server first
python3 otp_client.py              # Text messaging
python3 otp_voice_client.py        # Voice calls
```

## Contacts System

### Device ID Format

Every device has a unique 11-character ID:
- Characters: lowercase letters (a-z) and numbers (0-9)
- Length: exactly 11 characters
- Example: `user1234567`, `abc12def345`

### Adding Contacts

1. Open the Contacts app
2. Click "Add Contact"
3. Enter the contact's 11-character device ID
4. Optionally set a nickname
5. Click "Add Contact"

### Using Contacts

Once you have contacts:
1. Click on a contact to select them
2. Choose an action:
   - **📨 Message** - Opens text messenger with recipient pre-filled
   - **🎤 Voice Call** - Opens voice client ready to call
   - **✏️ Edit** - Change nickname or delete contact

### Data Storage

Contact data is stored locally in:
- `device_config.json` - Device ID and setup info
- `contacts.json` - Contact list with nicknames and notes
- `credentials.txt` - Username file for other apps (auto-generated)

## Voice Calls System

### How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    Voice Call Flow                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  User A                    Relay Server              User B │
│    │                            │                       │   │
│    │ 1. Create Room             │                       │   │
│    │ ─────────────────────────► │                       │   │
│    │                            │                       │   │
│    │ 2. Invite User B           │ 3. Forward Invite     │   │
│    │ ─────────────────────────► │ ─────────────────────►│   │
│    │                            │                       │   │
│    │                            │ 4. Join Room          │   │
│    │                            │ ◄─────────────────────│   │
│    │                            │                       │   │
│    │ 5. AES-encrypted audio     │                       │   │
│    │ ◄──────────────────────────┼───────────────────────│   │
│    │                            │                       │   │
└─────────────────────────────────────────────────────────────┘
```

### Voice Encryption Details

- **Algorithm**: AES-256-GCM (Galois/Counter Mode)
- **Key Derivation**: PBKDF2-HMAC-SHA256 (100,000 iterations)
- **Nonce**: 12 bytes, randomly generated per packet
- **Authentication**: Built-in with GCM mode

### Creating a Voice Call

1. **Start the server**: Launch `otp_relay_server_voice.py`
2. **Connect**: Both users connect to the server
3. **Create room**: One user creates a room with a password
4. **Share password**: Send the room ID and password through secure channel (use OTP text!)
5. **Join room**: Other user joins with room ID and password
6. **Talk**: Use Push-to-Talk (hold button or spacebar) to transmit

### Group Calls

The voice system supports unlimited participants per room:

1. Room creator invites users through the UI
2. Invited users receive a popup notification
3. All participants hear everyone else (automatic mixing)
4. Anyone can leave at any time
5. Room closes when last participant leaves

## Security Considerations

### Text Messaging (OTP)
- **Perfect secrecy** when OTP is truly random and used once
- OTP file must be distributed securely before use
- Each page is marked as used after encryption/decryption

### Voice Calls (AES)
- **Computational security** based on AES-256 strength
- Password-derived keys - use strong, unique passwords
- Salt is shared per-room to derive the same key
- Forward secrecy: each call uses a unique key

### Recommendations

1. **Generate OTP on the Pi 5** - Uses hardware RNG for true randomness
2. **Distribute OTP files in person** - USB drive, never over network
3. **Use strong voice passwords** - At least 16 characters
4. **Share voice passwords via OTP text** - Use the secure text channel

## Kiosk Mode

### VM Testing (Recommended First)

```bash
# Put all files in one folder
mkdir ~/otp_test
cp *.py ~/otp_test/
cd ~/otp_test

# Run setup
sudo ./setup_kiosk_vm_test.sh

# Reboot into kiosk
sudo reboot
```

**To exit**: Press Escape 3 times quickly

**To remove**:
```bash
sudo /root/remove_kiosk_test.sh
sudo reboot
```

### Production Lockdown (Pi 5)

⚠️ **Test in a VM first!** This makes significant system changes.

```bash
sudo ./setup_kiosk.sh
sudo reboot
```

### Recovery

If you need to regain access:

1. **Recovery mode**: Boot with recovery option, run `/root/disable_kiosk.sh`
2. **SSH**: If enabled, login remotely as your admin user
3. **Physical**: Hold Shift during boot for GRUB menu

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                      Kiosk Launcher                           │
│                            │                                  │
│                   ┌────────▼────────┐                         │
│                   │    CONTACTS     │  ◄── Central Hub        │
│                   │  otp_contacts   │                         │
│                   └────────┬────────┘                         │
│                            │                                  │
│         ┌──────────────────┼──────────────────┐              │
│         ▼                  ▼                  ▼              │
│  ┌──────────┐       ┌──────────┐       ┌──────────┐         │
│  │  Text    │       │  Voice   │       │  System  │         │
│  │ Messenger│       │  Client  │       │  Tools   │         │
│  └────┬─────┘       └────┬─────┘       └────┬─────┘         │
└───────┼──────────────────┼──────────────────┼────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
   otp_client.py    otp_voice_       otp_generator.py
                    client.py        otp_relay_server_voice.py
        │                  │                  │
        │                  │                  ▼
        │                  │            /dev/hwrng
        │                  │            (Pi 5 TRNG)
        ▼                  ▼
   ┌─────────────────────────────────────────────────────────┐
   │  Local Storage:                                         │
   │    device_config.json  ◄── Device ID (admin sets once)  │
   │    contacts.json       ◄── Contact list + nicknames     │
   │    otp_cipher.txt      ◄── True random OTP pages        │
   │    used_pages.txt      ◄── Used page tracking           │
   └─────────────────────────────────────────────────────────┘
   
   Network Protocol:
   ┌─────────────────────────────────────────────────────────┐
   │ Text:  recipient|otp_id:encrypted_hex                  │
   │ Voice: VOICE|room_id|sender|base64_aes_encrypted_audio │
   │ Room:  ROOM|command|room_id|...                        │
   └─────────────────────────────────────────────────────────┘
```

### User Workflow

```
┌──────────────────────────────────────────────────────────────┐
│                    Typical User Workflow                     │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. ADMIN SETUP (one-time)                                   │
│     └─► Launch otp_contacts.py                               │
│     └─► Enter device's unique 11-char ID                     │
│     └─► Give device to user                                  │
│                                                              │
│  2. USER ADDS CONTACTS                                       │
│     └─► Open Contacts app                                    │
│     └─► Click "Add Contact"                                  │
│     └─► Enter friend's 11-char device ID                     │
│     └─► Set nickname (e.g., "Mom", "Bob")                    │
│                                                              │
│  3. USER COMMUNICATES                                        │
│     └─► Select contact from list                             │
│     └─► Click "Message" or "Voice Call"                      │
│     └─► App opens with recipient pre-filled                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### No audio input/output
```bash
# Install PortAudio development files
sudo apt-get install portaudio19-dev

# Reinstall PyAudio
pip install --force-reinstall pyaudio --break-system-packages

# Check audio devices
python3 -c "import pyaudio; p = pyaudio.PyAudio(); print([p.get_device_info_by_index(i)['name'] for i in range(p.get_device_count())])"
```

### Cryptography import error
```bash
pip install --upgrade cryptography --break-system-packages
```

### Ngrok tunnel fails
```bash
# Make sure you have an ngrok account and auth token
ngrok authtoken YOUR_AUTH_TOKEN
```

### Hardware RNG not found
- Only available on Raspberry Pi 5
- Run generator with `sudo` for `/dev/hwrng` access
- For testing without Pi 5, modify `otp_generator.py` to use `/dev/urandom`

## Protocol Reference

### Text Message Format
```
recipient_id|otp_page_id:hex_encrypted_content
```

### Voice Protocol
```
# Create room
VOICE|room_id|sender_id|base64_encrypted_audio

# Room commands
ROOM|CREATE|room_id|salt_base64
ROOM|JOIN|room_id
ROOM|LEAVE|room_id
ROOM|INVITE|target_user|room_id|salt_base64

# Room responses
ROOM|SALT|salt_base64
ROOM|MEMBERS|user1,user2,user3
ROOM|JOINED|user_id
ROOM|LEFT|user_id
ROOM|ERROR|message
```

## License

This software is provided for educational purposes. Use responsibly and in compliance with all applicable laws.
