import os
import numpy as np
from astropy.io import fits
from tkinter import filedialog, messagebox

def set_calibration():
    folder_selected = filedialog.askdirectory(title="Select Folder Containing FIT/FITS Files")
    if not folder_selected:
        return None, None

    # Categorize FITS files
    lights, darks, flats, biases = categorize_files(folder_selected)

    if not lights:
        messagebox.showerror("Error", "No light frames found")
        return None, None

    # Process calibration
    calibrated_lights = process_calibration(lights, darks, flats, biases)

    # Ask if the user wants to save calibrated files
    save_files = messagebox.askyesno("Save Calibrated Files?", "Would you like to save the calibrated files?")
    if save_files:
        save_calibrated_files(calibrated_lights, lights, folder_selected)

    return calibrated_lights, lights

def categorize_files(folder):
    files = os.listdir(folder)
    lights, darks, flats, biases = [], [], [], []

    for file in files:
        if file.endswith(('.fit', '.fits')):
            filepath = os.path.join(folder, file)
            with fits.open(filepath) as hdul:
                header = hdul[0].header
                imagetyp = header.get('IMAGETYP', '').upper()
                if 'LIGHT' in imagetyp:
                    lights.append(filepath)
                elif 'DARK' in imagetyp:
                    darks.append(filepath)
                elif 'FLAT' in imagetyp:
                    flats.append(filepath)
                elif 'BIAS' in imagetyp:
                    biases.append(filepath)

    return lights, darks, flats, biases

def process_calibration(lights, darks, flats, biases):
    # Compute master bias, dark, and flat frames
    master_bias = np.median([fits.getdata(bias).astype(np.float64) for bias in biases], axis=0) if biases else None
    master_dark = (np.median([fits.getdata(dark).astype(np.float64) for dark in darks], axis=0) - master_bias) if darks and master_bias is not None else None
    master_flat = np.median([fits.getdata(flat).astype(np.float64) for flat in flats], axis=0) if flats else None

    if master_flat is not None:
        master_flat /= np.median(master_flat)  # Normalize the flat field

    calibrated_lights = []

    for light in lights:
        data = fits.getdata(light).astype(np.float64)
        if master_bias is not None:
            data -= master_bias
        if master_dark is not None:
            data -= master_dark
        if master_flat is not None:
            data /= master_flat

        calibrated_lights.append(data)

    return calibrated_lights

def save_calibrated_files(calibrated_lights, lights, folder_selected):
    calibrated_folder = os.path.join(folder_selected, "Calibrated files")
    os.makedirs(calibrated_folder, exist_ok=True)

    for i, light in enumerate(lights):
        hdu = fits.PrimaryHDU(calibrated_lights[i])
        output_path = os.path.join(calibrated_folder, f"calibrated_{os.path.basename(light)}")
        hdu.writeto(output_path, overwrite=True)

    messagebox.showinfo("Success", f"Calibrated files saved in {calibrated_folder}")
