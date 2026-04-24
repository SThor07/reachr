import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import Client, create_client

from routers import interview

load_dotenv()

app = FastAPI(
    title="Reachr API",
    description="AI that screens so you don't have to",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase: Optional[Client] = None


@app.on_event("startup")
async def startup():
    global supabase
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if url and key:
        supabase = create_client(url, key)


app.include_router(interview.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "app": "Reachr"}


@app.get("/db-health")
async def db_health():
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not connected")
    try:
        result = supabase.table("agencies").select("*", count="exact").execute()
        return {"status": "ok", "agency_count": result.count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {
        "app": "Reachr",
        "tagline": "AI that screens so you don't have to",
        "interviewer": "Maya",
        "version": "0.1.0",
    }
