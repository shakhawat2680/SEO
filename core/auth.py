from fastapi import Header, HTTPException

API_KEYS = {
    "cashog-key": "cashog"
}


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return API_KEYS[x_api_key]
