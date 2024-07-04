import requests
import configparser

def get_auth_token():
    config = configparser.ConfigParser()
    config.read('config.ini')

    url = f"{config['API']['bhtom_url']}/api/token-auth/"
    payload = {
        'username': config['API']['username'],
        'password': config['API']['password']
    }
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()['token']
