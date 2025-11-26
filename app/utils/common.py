import sys
import os
import subprocess
from pathlib import Path
import segno
from .log import logger

def open_folder(path: Path):
    """Open folder in file explorer."""
    try:
        if os.name == 'nt':
            os.startfile(str(path))
        elif os.name == 'posix':
            if sys.platform == 'darwin':
                subprocess.run(['open', str(path)])
            else:
                subprocess.run(['xdg-open', str(path)])
    except Exception as e:
        logger.error(f"Failed to open folder: {e}")

def save_qr_and_open(url: str, filename: str = "login_qr.png"):
    """Generate QR code, save to file, and open it."""
    try:
        qr = segno.make_qr(url)
        path = Path(filename)
        qr.save(str(path), scale=10)
        
        # Try to open the file/folder
        open_folder(path.parent) 
        if sys.platform == 'darwin':
             subprocess.run(['open', str(path)])
        elif os.name == 'nt':
             os.startfile(str(path))
             
        # Print to terminal as fallback/convenience
        print("\nScan this QR code:")
        qr.terminal(compact=True)
        print(f"\nQR Code saved to: {path.absolute()}\n")
        
        return path
    except Exception as e:
        logger.error(f"Failed to save QR: {e}")
        return None
