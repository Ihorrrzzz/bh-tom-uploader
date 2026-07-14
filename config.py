import configparser
import os

# Read config.ini located next to this file, so the working directory does not matter.
_config = configparser.ConfigParser()
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
_config.read(_config_path)

# Base URL of the BHTOM web/API service (targets, auth, photometry download, ...).
BHTOM_URL = _config.get('API', 'bhtom_url', fallback='https://bh-tom2.astrouw.edu.pl').rstrip('/')

# Base URL of the separate upload microservice (data product / FITS upload).
UPLOAD_URL = _config.get('API', 'upload_url', fallback='https://uploadsvc2.bh-tom2.astrouw.edu.pl').rstrip('/')
