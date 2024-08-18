from astropy.io import fits
import numpy as np

def load_fits_files(file_paths):
    ccds = []
    for path in file_paths:
        with fits.open(path) as hdul:
            ccds.append(hdul[0].data)
    return ccds

def create_master_bias(bias_ccds):
    return np.median(bias_ccds, axis=0)

def create_master_dark(dark_ccds, master_bias=None):
    master_dark = np.median(dark_ccds, axis=0)
    if master_bias is not None:
        master_dark -= master_bias
    return master_dark

def create_master_flat(flat_ccds, master_bias=None, master_dark=None):
    master_flat = np.median(flat_ccds, axis=0)
    if master_bias is not None:
        master_flat -= master_bias
    if master_dark is not None:
        master_flat -= master_dark
    return master_flat / np.median(master_flat)

def calibrate_image(image_path, master_bias=None, master_dark=None, master_flat=None):
    with fits.open(image_path) as hdul:
        image_data = hdul[0].data
        if master_bias is not None:
            image_data -= master_bias
        if master_dark is not None:
            image_data -= master_dark
        if master_flat is not None:
            image_data /= master_flat
        return image_data

def save_fits(data, output_path):
    hdu = fits.PrimaryHDU(data)
    hdu.writeto(output_path, overwrite=True)
