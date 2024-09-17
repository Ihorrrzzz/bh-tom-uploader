import os
import requests  # Ensure requests is imported here
import tkinter as tk
from tkinter import messagebox, simpledialog
from astropy.io import fits
from light_curve import download_photometry_request  # Import photometry function from light_curve

def create_target(name, ra, dec, epoch, classification, discovery_date, importance, cadence, token):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {token}",
    }

    data = {
        "name": name,
        "ra": ra,
        "dec": dec,
        "epoch": epoch if epoch else 2000.0,
        "classification": classification if classification else "Unknown",
        "discovery_date": discovery_date if discovery_date else "2023-01-01T00:00:01Z",
        "importance": importance if importance else 9.97,
        "cadence": cadence if cadence else 1.0,
    }

    api_url = "https://bh-tom2.astrolabs.pl/targets/createTarget/"
    response = requests.post(api_url, headers=headers, json=data)
    response_json = response.json()
    print("Create Target Response:", response_json)

    if response.status_code == 201:  # HTTP status code 201 indicates successful creation
        messagebox.showinfo("Target Created", f"Target '{name}' has been successfully created.")
        return True
    else:
        messagebox.showerror("Target Creation Failed", f"Failed to create target '{name}'.\nDetails: {response_json}")
        return False

# Extract RA and DEC from FITS file header
def extract_ra_dec_from_fits(fits_file):
    try:
        with fits.open(fits_file) as hdul:
            header = hdul[0].header
            ra = header.get('RA')
            dec = header.get('DEC')
            if ra is not None and dec is not None:
                return float(ra), float(dec)
    except Exception as e:
        print(f"Error extracting RA/DEC from {fits_file}: {e}")
    return None, None

def upload_calibrated_files(calibrated_image_paths, token, target_name, app):
    observatory_name = 'AZT-8_C4-16000'
    filter_name = 'GaiaSP/any'

    for calibrated_image_path in calibrated_image_paths:
        with open(calibrated_image_path, 'rb') as f:
            print("Sending...")

            data = {
                'target': target_name,
                'filter': filter_name,
                'data_product_type': 'fits_file',
                'dry_run': 'False',
                'observatory': observatory_name,
            }

            response = requests.post(
                url='https://uploadsvc2.astrolabs.pl/upload/',
                headers={
                    'Authorization': "Token " + str(token)
                },
                data=data,
                files={'files': f}
            )
            result = response.json()
            print("Upload Response:", result)

            if 'target' in result and any("does not exist in the bhtom" in msg for msg in result['target']):
                messagebox.showwarning("Target Not Found",
                                       f"Target '{target_name}' does not exist. Please enter the necessary details to create it.")

                # Try to extract RA and DEC from the first calibrated image header
                ra, dec = extract_ra_dec_from_fits(calibrated_image_path)

                if ra is None or dec is None:
                    # If RA/DEC not in header, prompt the user
                    ra = simpledialog.askstring("Input", "Enter Right Ascension (RA) for the target:", parent=app)
                    dec = simpledialog.askstring("Input", "Enter Declination (Dec) for the target:", parent=app)
                    if ra is None or dec is None:
                        messagebox.showerror("Input Error", "RA and Dec are mandatory fields. Target creation aborted.")
                        return
                    ra = float(ra)
                    dec = float(dec)

                # Additional details from the user
                epoch = simpledialog.askstring("Input", "Enter Epoch (default 2000.0):", parent=app)
                classification = simpledialog.askstring("Input", "Enter Classification (default 'Unknown'):",
                                                        parent=app)
                discovery_date = simpledialog.askstring("Input",
                                                        "Enter Discovery Date (default '2023-01-01T00:00:01Z'):",
                                                        parent=app)
                importance = simpledialog.askstring("Input", "Enter Importance (default 9.97):", parent=app)
                cadence = simpledialog.askstring("Input", "Enter Cadence (default 1.0):", parent=app)

                if create_target(
                        name=target_name,
                        ra=ra,
                        dec=dec,
                        epoch=float(epoch) if epoch else None,
                        classification=classification,
                        discovery_date=discovery_date,
                        importance=float(importance) if importance else None,
                        cadence=float(cadence) if cadence else None,
                        token=token,
                ):
                    with open(calibrated_image_path, 'rb') as retry_f:
                        retry_response = requests.post(
                            url='https://uploadsvc2.astrolabs.pl/upload/',
                            headers={
                                'Authorization': "Token " + str(token)
                            },
                            data=data,
                            files={'files': retry_f}
                        )
                        retry_result = retry_response.json()
                        print("Retry Upload Response:", retry_result)

                        if 'target' not in retry_result:
                            messagebox.showinfo("Upload Successful",
                                                f"Calibrated file successfully uploaded to BHTOM under target '{target_name}'.")
                            download_photometry_request(token, target_name, app)
                        else:
                            messagebox.showerror("Upload Failed",
                                                 f"Failed to upload calibrated file after target creation.\nDetails: {retry_result}")
                        return
            elif 'non_field_errors' in result:
                messagebox.showerror("Upload Error", f"Non-field error: {result['non_field_errors']}")
                return

    messagebox.showinfo("Upload Completed", "All calibrated files have been uploaded to BHTOM.")
    download_photometry_request(token, target_name, app)
