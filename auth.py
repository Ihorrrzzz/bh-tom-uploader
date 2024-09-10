import requests

def get_auth_token(username, password):
    url = 'https://bh-tom2.astrolabs.pl/api/token-auth/'
    payload = {
        "username": username,
        "password": password
    }

    response = requests.post(url, json=payload)
    response.raise_for_status()  # Raise an error for bad status codes

    # Parse the token from the JSON response
    token = response.json().get('token')
    return token
