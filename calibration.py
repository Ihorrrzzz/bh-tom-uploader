from astropy.io import fits
import numpy as np


def calibrate_image(image_path):
    with fits.open(image_path) as hdul:
        image_data = hdul[0].data

        # Example calibration step: subtracting the median value
        # More sophisticated calibration should involve dark frames, bias frames, and flat fields
        image_data = image_data - np.median(image_data)

        calibrated_image_path = image_path.replace(".fits", "_calibrated.fits").replace(".fit", "_calibrated.fit")
        fits.writeto(calibrated_image_path, image_data, hdul[0].header, overwrite=True)

    return calibrated_image_path
