#!/usr/bin/env python3
"""
OTP Generator - True Random Page Generator
Generates OTP cipher pages using hardware RNG (Pi) or /dev/urandom (Linux).

On Raspberry Pi: Uses /dev/hwrng for true hardware randomness
On other Linux: Uses /dev/urandom (cryptographically secure PRNG)

Usage: python3 otp_generator.py
"""

import tkinter as tk
from tkinter import messagebox
import string
import os
import sys
from pathlib import Path

# --- CONFIGURATION ---
PI_HWRNG_DEVICE = "/dev/hwrng"
URANDOM_DEVICE = "/dev/urandom"
OUTPUT_FILENAME = "otp_cipher.txt"
PAGE_LENGTH = 3500
PAGE_ID_LENGTH = 8

# --- CORE GENERATION LOGIC ---

def generate_random_page(rng_file, length, include_id=True):
    """
    Generate a string using randomness from the RNG device.
    Uses rejection sampling to map 0-255 bytes to the character set
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
        # Read a chunk of raw entropy
        chunk_size = needed * 4  
        raw_bytes = rng_file.read(chunk_size)
        
        if not raw_bytes:
            raise IOError("Failed to read from RNG device.")
            
        for byte in raw_bytes:
            if byte < limit:
                # Map byte to character index
                char_index = byte % charset_len
                result.append(chars[char_index])
                
                if len(result) == length:
                    break
                    
        needed = length - len(result)
    
    page_content = "".join(result)
    
    # Add page ID prefix if requested
    if include_id:
        page_id = page_content[:PAGE_ID_LENGTH]
        return page_id + page_content
    
    return page_content


def get_rng_device():
    """
    Determine which RNG device to use.
    Returns (device_path, device_name, is_hardware)
    """
    # Try hardware RNG first (Raspberry Pi)
    if os.path.exists(PI_HWRNG_DEVICE):
        try:
            with open(PI_HWRNG_DEVICE, 'rb') as f:
                f.read(1)  # Test read
            return PI_HWRNG_DEVICE, "Hardware RNG (Pi)", True
        except PermissionError:
            # Hardware RNG exists but needs sudo
            return PI_HWRNG_DEVICE, "Hardware RNG (Pi) - needs sudo", True
        except:
            pass
    
    # Fall back to urandom
    if os.path.exists(URANDOM_DEVICE):
        return URANDOM_DEVICE, "/dev/urandom (CSPRNG)", False
    
    return None, "No RNG available", False


def generate_otp_file(num_pages, rng_device, status_callback=None):
    """
    Generate an OTP file using the specified RNG device.
    """
    output_path = Path(OUTPUT_FILENAME)
    
    try:
        with open(rng_device, "rb") as rng, output_path.open("w", encoding="utf-8") as file:
            for i in range(1, num_pages + 1):
                # Generate random content with page ID
                otp_page = generate_random_page(rng, PAGE_LENGTH)
                file.write(otp_page + "\n")
                
                # Update UI periodically
                if status_callback and i % 10 == 0:
                    status_callback(i, num_pages)
                    
    except PermissionError:
        raise PermissionError(f"Permission denied accessing {rng_device}. Try running with 'sudo'.")

    return output_path.resolve()


# --- GUI CLASS ---

class OTPGeneratorApp:
    def __init__(self, master):
        self.master = master
        master.title("OTP Generator")
        master.geometry("450x280")
        master.configure(bg='#0d1117')
        
        # Detect RNG device
        self.rng_device, self.rng_name, self.is_hardware = get_rng_device()
        
        # Header
        tk.Label(
            master, 
            text="OTP Cipher Generator",
            font=("Helvetica", 16, "bold"),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(pady=(15, 5))
        
        # RNG Status
        rng_color = '#3fb950' if self.rng_device else '#f85149'
        if self.is_hardware and "sudo" in self.rng_name:
            rng_color = '#d29922'
            
        tk.Label(
            master,
            text=f"RNG: {self.rng_name}",
            font=("Consolas", 10),
            fg=rng_color,
            bg='#0d1117'
        ).pack(pady=(0, 10))

        # Output file
        tk.Label(
            master, 
            text=f"Output: {OUTPUT_FILENAME}",
            font=("Consolas", 10),
            fg='#8b949e',
            bg='#0d1117'
        ).pack(pady=(0, 15))

        # Frame for Input
        input_frame = tk.Frame(master, bg='#0d1117')
        input_frame.pack(pady=5)

        tk.Label(
            input_frame, 
            text="Number of Pages:",
            font=("Helvetica", 11),
            fg='#c9d1d9',
            bg='#0d1117'
        ).pack(side="left", padx=5)
        
        self.num_pages_var = tk.StringVar(value="1000")
        entry = tk.Entry(
            input_frame, 
            textvariable=self.num_pages_var, 
            width=10,
            font=("Consolas", 11),
            bg='#21262d',
            fg='#c9d1d9',
            insertbackground='#c9d1d9',
            relief='flat'
        )
        entry.pack(side="left", ipady=5, ipadx=5)

        # Generate Button
        self.generate_button = tk.Button(
            master, 
            text="Generate OTP File",
            command=self.generate_otp_action, 
            font=("Helvetica", 12, "bold"),
            bg='#238636',
            fg='white',
            activebackground='#2ea043',
            activeforeground='white',
            relief='flat',
            padx=20,
            pady=10,
            cursor='hand2'
        )
        self.generate_button.pack(pady=20)
        
        # Disable button if no RNG available
        if not self.rng_device:
            self.generate_button.config(state='disabled', bg='#484f58')

        # Status Label
        self.status_label = tk.Label(
            master, 
            text="Ready",
            font=("Consolas", 10),
            fg='#8b949e',
            bg='#0d1117'
        )
        self.status_label.pack(pady=5)

    def update_status(self, current, total):
        """Callback to update GUI during generation."""
        self.status_label.config(text=f"Generating... {current}/{total} pages")
        self.master.update()

    def generate_otp_action(self):
        # Validate num_pages
        try:
            num_pages = int(self.num_pages_var.get().strip())
            if num_pages <= 0: 
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive integer.")
            return

        # Disable button during generation
        self.generate_button.config(state="disabled")
        self.status_label.config(text=f"Using {self.rng_name}...", fg='#58a6ff')
        self.master.update()

        try:
            output_path = generate_otp_file(
                num_pages=num_pages,
                rng_device=self.rng_device,
                status_callback=self.update_status
            )
            self.status_label.config(text=f"Done! Saved {num_pages} pages", fg='#3fb950')
            messagebox.showinfo(
                "Success", 
                f"Generated {num_pages} pages.\n\nSaved to: {output_path}\n\nRNG used: {self.rng_name}"
            )
            
        except PermissionError:
            self.status_label.config(text="Error: Permission denied", fg='#f85149')
            messagebox.showerror(
                "Permission Error", 
                f"Cannot access {self.rng_device}.\n\nTry running with: sudo python3 otp_generator.py"
            )
        except Exception as e:
            self.status_label.config(text="Error occurred", fg='#f85149')
            messagebox.showerror("Error", f"An error occurred:\n{e}")
        finally:
            self.generate_button.config(state="normal")


def main():
    root = tk.Tk()
    app = OTPGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
