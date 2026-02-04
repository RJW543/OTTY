# OTP Management System v2 - Per-Contact Cipher Pads

A secure one-time pad management system where **each contact has their own completely separate cipher pad**.

## Key Architecture

### Per-Contact Cipher Pads

**CRITICAL**: A pad shared with Alice is **NEVER** used with Bob.

Each contact relationship has its own unique `cipher.txt` file containing pages that are:
- Generated specifically for that contact
- Shared only with that contact
- Used only when communicating with that contact

### Folder Structure
```
otp_data/
└── contacts/
    ├── alice123abc/
    │   ├── cipher.txt          # THE unique pad for Alice (ONLY Alice)
    │   ├── used_pages.txt      # Track which pages have been used
    │   └── info.json           # Metadata
    ├── bob456def78/
    │   ├── cipher.txt          # Completely DIFFERENT pad for Bob
    │   ├── used_pages.txt
    │   └── info.json
    └── charlie789/
        ├── cipher.txt          # Another unique pad for Charlie
        └── ...
```

### Security Benefits
1. **Complete Cryptographic Separation** - Each contact relationship is isolated
2. **No Cross-Contamination** - Compromise of one pad doesn't affect others
3. **Clear Audit Trail** - Easy to see which pages were used with whom
4. **Proper Key Management** - Pads are tied to identities, not floating in a pool

## Components

### `otp_manager.py` - Pad Management UI
Central interface for managing per-contact cipher pads.

**Features:**
- Generate new pads for specific contacts
- View pad statistics per contact
- Delete used pages to save space
- Delete entire pads
- Export pads for backup

**Usage:**
```bash
python3 otp_manager.py
```

### `otp_bluetooth_share.py` - Bluetooth Transfer
Share cipher pads with contacts via Bluetooth when meeting in person.

**Workflow:**
1. You generate a pad for "Bob" on your device
2. You meet Bob in person
3. You send the pad to Bob via Bluetooth
4. Bob receives it and saves it as his pad for "You"
5. Now both have identical pads for communicating

**Usage:**
```bash
python3 otp_bluetooth_share.py
```

### `otp_client_v2.py` - Messaging Client
Updated messaging client with per-contact pad encryption.

**Features:**
- Automatically uses the correct contact's pad
- Shows page count per recipient
- Warns when pages are running low
- Direct link to OTP Manager

**Usage:**
```bash
python3 otp_client_v2.py
```

### `otp_helper.py` - Integration Module
Helper module for integrating per-contact pads with other applications.

**API:**
```python
from otp_helper import OTPHelper

helper = OTPHelper()

# Check if contact has a pad
if helper.contact_has_pad("alice123"):
    # Get a page to encrypt a message
    page_id, content = helper.get_page_for_contact("alice123")
    
# Find a page to decrypt a received message
content = helper.find_page_for_decryption("ABCD1234", "alice123")

# Get statistics
stats = helper.get_statistics()
```

## Workflow

### Setting Up Communication with a New Contact

1. **Generate a Pad**
   - Open OTP Manager
   - Click "New Pad for Contact"
   - Select the contact
   - Generate (e.g., 1000 pages)

2. **Meet in Person**
   - Physical meeting is required for security
   - Verify each other's identity

3. **Share via Bluetooth**
   - Sender: Opens Bluetooth Share → Send tab → Select contact's pad → Scan → Send
   - Receiver: Opens Bluetooth Share → Receive tab → Select who's sending → Start Receiving

4. **Ready to Communicate**
   - Both users now have identical pads in their respective contact folders
   - Messages are encrypted using pages from that specific pad

### Sending a Message

1. Open `otp_client_v2.py`
2. Connect to relay server
3. Enter recipient ID
4. Type message and send
5. Client automatically:
   - Finds the recipient's cipher pad
   - Gets the next unused page
   - Encrypts the message
   - Marks the page as used

### Receiving a Message

1. Message arrives with: sender ID, page ID, encrypted content
2. Client looks up the page in the **sender's** pad folder
3. Decrypts using that specific page
4. Marks the page as used

## Security Considerations

### Why Not a Shared Pool?
A shared pool where pages are "assigned" to contacts is **dangerous**:
- Risk of accidentally using the same page with different contacts
- No cryptographic isolation between relationships
- Complex tracking that could have bugs

With per-contact pads:
- Each `cipher.txt` file is unique
- No possibility of cross-contamination
- Simple, auditable structure

### Physical Verification Required
Bluetooth sharing should only happen when:
- You have physically met the contact
- You have verified their identity
- You are in a secure location

### Best Practices
1. Generate large pads (1000+ pages per contact)
2. Monitor page counts and replenish before running out
3. Meet in person to share new pads when needed
4. Consider deleting used pages to save storage

## File Descriptions

| File | Description |
|------|-------------|
| `otp_manager.py` | GUI for managing per-contact pads |
| `otp_bluetooth_share.py` | Bluetooth pad transfer tool |
| `otp_client_v2.py` | Messaging client with per-contact pads |
| `otp_helper.py` | Helper module for integration |
| `setup_bluetooth.sh` | Bluetooth dependency installer |

## Dependencies

```bash
# System packages
sudo apt-get install bluetooth bluez libbluetooth-dev python3-tk

# Python packages  
pip install pybluez pyngrok
```

## Troubleshooting

### "No cipher pad for contact"
- Open OTP Manager
- Generate a new pad for that contact
- Or receive their pad via Bluetooth

### "Cannot decrypt - no matching page"
- You don't have the sender's cipher pad
- Meet them and exchange pads via Bluetooth

### Bluetooth not working
- Run `sudo ./setup_bluetooth.sh`
- Make device discoverable: `bt-discoverable`
- Check status: `bt-status`

## License

For educational and lawful use only. Users are responsible for compliance with applicable laws.
