import requests
from config import BHTOM_URL

def get_auth_token(username, password):
    url = f'{BHTOM_URL}/api/token-auth/'
    payload = {
        "username": username,
        "password": password
    }

    response = requests.post(url, json=payload)
    response.raise_for_status()  # Raise an error for bad status codes

    # Parse the token from the JSON response
    token = response.json().get('token')
    return token