import os
import sys
import time

# CONFIGURATION
OUTPUT_FILE = "otp_book.txt"
TOTAL_PAGES = 10000
CHARS_PER_PAGE = 3500
# Hardware device for True Randomness on Pi 5
RNG_DEVICE = "/dev/hwrng" 

def generate_otp():
    # 1. Calculate limits for Rejection Sampling to remove bias
    # We want chars A-Z (26 options). 
    # The max multiple of 26 that fits in a byte (0-255) is 234 (26 * 9).
    # To ensure perfect fairness, we must discard raw bytes >= 234.
    limit = 234 
    
    print(f"--- Starting True Random OTP Generation ---")
    print(f"Source: {RNG_DEVICE} (Broadcom BCM2712 HWRNG)")
    print(f"Target: {TOTAL_PAGES} pages of {CHARS_PER_PAGE} characters.")
    print(f"Output: {OUTPUT_FILE}\n")

    try:
        # Open the hardware device in binary read mode
        with open(RNG_DEVICE, "rb") as rng, open(OUTPUT_FILE, "w") as out:
            
            start_time = time.time()
            
            for page in range(1, TOTAL_PAGES + 1):
                chars_collected = 0
                page_buffer = []
                
                # Header for the page
                out.write(f"\n--- PAGE {page} ---\n")
                
                while chars_collected < CHARS_PER_PAGE:
                    # Read a chunk of raw bytes from hardware
                    # We read more than needed to account for discarded bytes
                    needed = CHARS_PER_PAGE - chars_collected
                    raw_chunk = rng.read(needed + 500) 
                    
                    if not raw_chunk:
                        print("Error: Could not read from hardware device.")
                        sys.exit(1)

                    for byte in raw_chunk:
                        # Rejection Sampling: Discard bytes that create bias
                        if byte < limit:
                            # Convert 0-233 range to 0-25 (A-Z)
                            char_code = byte % 26
                            # Convert to ASCII character
                            page_buffer.append(chr(65 + char_code))
                            chars_collected += 1
                            
                            if chars_collected == CHARS_PER_PAGE:
                                break
                
                # Write the page to file
                # Optional: Format into blocks of 5 for readability
                # data_str = "".join(page_buffer)
                # formatted_data = " ".join(data_str[i:i+5] for i in range(0, len(data_str), 5))
                # out.write(formatted_data)
                
                # Standard write (continuous stream per page)
                out.write("".join(page_buffer))
                out.write("\n")

                # Progress indicator every 100 pages
                if page % 100 == 0:
                    elapsed = time.time() - start_time
                    print(f"Generated Page {page}/{TOTAL_PAGES} ({elapsed:.1f}s elapsed)")

    except PermissionError:
        print("ERROR: Permission denied.")
        print(f"You must run this script with sudo to access {RNG_DEVICE}.")
        print("Try: sudo python3 generate_otp.py")
    except FileNotFoundError:
        print(f"ERROR: {RNG_DEVICE} not found.")
        print("Are you running this on a Raspberry Pi?")

    print(f"\nDone! Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_otp()