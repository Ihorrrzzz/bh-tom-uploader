import requests
import configparser
from auth import get_auth_token


def upload_to_bhtom(image_path, token):
    config = configparser.ConfigParser()
    config.read('config.ini')

    url = f"{config['API']['bhtom_url']}/upload"
    files = {'file': open(image_path, 'rb')}
    headers = {
        'Authorization': f'Token {token}'
    }

    response = requests.post(url, files=files, headers=headers)
    response.raise_for_status()

    try:
        return response.json()
    except requests.exceptions.JSONDecodeError:
        print("Response content:", response.content)
        raise


def get_light_curve_data(upload_response, token):
    light_curve_url = upload_response.get('light_curve_url')
    if not light_curve_url:
        print("No light curve URL in response:", upload_response)
        return None

    headers = {
        'Authorization': f'Token {token}'
    }
    response = requests.get(light_curve_url, headers=headers)
    response.raise_for_status()

    try:
        return response.json()
    except requests.exceptions.JSONDecodeError:
        print("Response content:", response.content)
        raise
