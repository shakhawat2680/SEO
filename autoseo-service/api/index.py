from fastapi import FastAPI

app = FastAPI()  # MUST be named 'app'

@app.get("/")
def home():
    return {"status": "SEO Engine Running"}
