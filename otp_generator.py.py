import tkinter as tk
from tkinter import messagebox
import string
import os
import sys
from pathlib import Path

# --- CONFIGURATION ---
PI_HWRNG_DEVICE = "/dev/hwrng"
OUTPUT_FILENAME = "otp_cipher.txt"
PAGE_LENGTH = 3500

# --- CORE GENERATION LOGIC ---

def generate_hwrng_page(rng_file, length):
    """
    Generate a string using TRUE hardware randomness from the Pi 5.
    Uses rejection sampling to map 0-255 bytes to the 68-character set
    without bias.
    """
    # Character set: A-Z, 0-9, and punctuation (Total: 68 chars)
    chars = string.ascii_uppercase + string.digits + string.punctuation
    charset_len = len(chars)  # 68
    
    # Rejection Sampling Math:
    # We want uniform distribution for 68 options.
    # The max multiple of 68 that fits in a byte (0-255) is 204 (68 * 3).
    # We must discard any byte >= 204 to maintain perfect cryptographic fairness.
    limit = 204
    
    result = []
    needed = length
    
    while len(result) < length:
        # Read a chunk of raw entropy. We read 4x needed to minimize disk I/O
        # and account for the discarded bytes.
        chunk_size = needed * 4  
        raw_bytes = rng_file.read(chunk_size)
        
        if not raw_bytes:
            raise IOError("Failed to read from hardware RNG device.")
            
        for byte in raw_bytes:
            if byte < limit:
                # Map byte to character index
                char_index = byte % charset_len
                result.append(chars[char_index])
                
                if len(result) == length:
                    break
                    
        needed = length - len(result)
        
    return "".join(result)

def generate_otp_file(num_pages, status_callback=None):
    """
    Generate an OTP file using only the Pi 5 Hardware RNG.
    """
    output_path = Path(OUTPUT_FILENAME)
    
    # Check for the hardware device before starting
    if not os.path.exists(PI_HWRNG_DEVICE):
        raise FileNotFoundError(f"Device {PI_HWRNG_DEVICE} not found. Are you on a Raspberry Pi?")

    try:
        # Open hardware device (rb) and output file (w)
        with open(PI_HWRNG_DEVICE, "rb") as rng, output_path.open("w", encoding="utf-8") as file:
            
            for i in range(1, num_pages + 1):
                # Generate true random content
                otp_page = generate_hwrng_page(rng, PAGE_LENGTH)
                file.write(otp_page + "\n")
                
                # Update UI every 10 pages to keep interface responsive
                if status_callback and i % 10 == 0:
                    status_callback(i, num_pages)
                    
    except PermissionError:
        raise PermissionError(f"Permission denied accessing {PI_HWRNG_DEVICE}. Run script with 'sudo'.")

    return output_path.resolve()


# --- GUI CLASS ---

class OTPGeneratorApp:
    def __init__(self, master):
        self.master = master
        master.title("True Random OTP Generator (Pi 5)")
        master.geometry("400x200")

        # Label: Output File
        tk.Label(master, text=f"Output File: {OUTPUT_FILENAME}", font=("Arial", 10, "bold")).pack(pady=10)

        # Frame for Input
        input_frame = tk.Frame(master)
        input_frame.pack(pady=5)

        tk.Label(input_frame, text="Number of Pages:").pack(side="left", padx=5)
        self.num_pages_var = tk.StringVar(value="10000")
        tk.Entry(input_frame, textvariable=self.num_pages_var, width=10).pack(side="left")

        # Generate Button
        self.generate_button = tk.Button(master, text="Generate True Random File", 
                                         command=self.generate_otp_action, bg="#dddddd")
        self.generate_button.pack(pady=15)

        # Status Label
        self.status_label = tk.Label(master, text="Ready", fg="blue")
        self.status_label.pack(pady=5)

    def update_status(self, current, total):
        """Callback to update GUI during the heavy loop."""
        self.status_label.config(text=f"Generating... {current}/{total} pages")
        self.master.update() # Force GUI refresh

    def generate_otp_action(self):
        # Validate num_pages
        try:
            num_pages = int(self.num_pages_var.get().strip())
            if num_pages <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive integer for pages.")
            return

        # Disable button during generation
        self.generate_button.config(state="disabled")
        self.status_label.config(text="Initializing Hardware RNG...", fg="blue")
        self.master.update()

        try:
            output_path = generate_otp_file(
                num_pages=num_pages,
                status_callback=self.update_status
            )
            self.status_label.config(text=f"Done! Saved to {OUTPUT_FILENAME}", fg="green")
            messagebox.showinfo("Success", f"Successfully generated {num_pages} pages.\nSaved to: {output_path}")
            
        except PermissionError:
            messagebox.showerror("Permission Error", "You must run this script with 'sudo' to access the Hardware RNG.")
            self.status_label.config(text="Error: Permission denied (use sudo)", fg="red")
        except FileNotFoundError:
             messagebox.showerror("Hardware Error", "Could not find /dev/hwrng.\nAre you running this on the Raspberry Pi?")
             self.status_label.config(text="Error: Hardware device missing", fg="red")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred:\n{e}")
            self.status_label.config(text="Error occurred", fg="red")
        finally:
            self.generate_button.config(state="normal")

def main():
    root = tk.Tk()
    app = OTPGeneratorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()