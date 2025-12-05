import os
from typing import List, Dict, Any, Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.ukri import scrape_ukri
from app.services.nihr import scrape_nihr
from app.services.catapult import scrape_catapult


app = FastAPI(title="Grant Scraper Service")


def _get_existing_grants(source: str) -> Dict[str, Dict[str, Any]]:
  """Fetch existing grants for a source to help optimize scraping."""
  django_url = os.getenv("DJANGO_API_URL", "http://localhost:8000")
  api_url = f"{django_url.rstrip('/')}/api/grants"
  api_key = os.getenv("SCRAPER_API_KEY", "")

  headers = {
      "Authorization": f"Bearer {api_key}",
      "Content-Type": "application/json",
  }

  try:
    resp = requests.get(api_url, params={"source": source}, headers=headers, timeout=10)
    if resp.status_code == 200:
      data = resp.json()
      # Return a dict keyed by URL for quick lookup
      return {grant["url"]: grant for grant in data.get("grants", [])}
  except Exception as e:
    print(f"Warning: Could not fetch existing grants for {source}: {e}")
  
  return {}


def _post_to_django(grants: List[Dict[str, Any]], log_id: Optional[int] = None) -> Dict[str, Any]:
  # Default to localhost for local development, web for Docker
  django_url = os.getenv("DJANGO_API_URL", "http://localhost:8000")
  api_url = f"{django_url.rstrip('/')}/api/grants/upsert"
  api_key = os.getenv("SCRAPER_API_KEY", "")

  headers = {
      "Authorization": f"Bearer {api_key}",
      "Content-Type": "application/json",
  }

  payload = {"grants": grants}
  if log_id:
    payload["log_id"] = log_id

  resp = requests.post(api_url, json=payload, headers=headers, timeout=300)
  if resp.status_code != 200:
    raise HTTPException(status_code=resp.status_code, detail=resp.text)
  return resp.json()


def run_ukri_job(log_id: Optional[int] = None) -> Dict[str, Any]:
  try:
    # Fetch existing grants to help optimize
    existing_grants = _get_existing_grants("ukri")
    grants = scrape_ukri(existing_grants=existing_grants)
    if not grants:
      return {"message": "No grants found", "created": 0, "updated": 0, "skipped": 0}
    return _post_to_django(grants, log_id=log_id)
  except Exception as e:
    print(f"Error in run_ukri_job: {e}")
    raise HTTPException(status_code=500, detail=f"UKRI scraper failed: {str(e)}")


def run_nihr_job(log_id: Optional[int] = None) -> Dict[str, Any]:
  try:
    # Fetch existing grants to help optimize
    existing_grants = _get_existing_grants("nihr")
    grants = scrape_nihr(existing_grants=existing_grants)
    if not grants:
      return {"message": "No grants found", "created": 0, "updated": 0, "skipped": 0}
    return _post_to_django(grants, log_id=log_id)
  except Exception as e:
    print(f"Error in run_nihr_job: {e}")
    raise HTTPException(status_code=500, detail=f"NIHR scraper failed: {str(e)}")


def run_catapult_job(log_id: Optional[int] = None) -> Dict[str, Any]:
  try:
    # Fetch existing grants to help optimize
    existing_grants = _get_existing_grants("catapult")
    grants = scrape_catapult(existing_grants=existing_grants)
    if not grants:
      return {"message": "No grants found", "created": 0, "updated": 0, "skipped": 0}
    return _post_to_django(grants, log_id=log_id)
  except Exception as e:
    print(f"Error in run_catapult_job: {e}")
    raise HTTPException(status_code=500, detail=f"Catapult scraper failed: {str(e)}")


@app.get("/health")
def health():
  return {"status": "ok"}


@app.post("/run/ukri")
async def run_ukri(request: Request):
  try:
    body = await request.json()
    log_id = body.get("log_id") if isinstance(body, dict) else None
  except:
    log_id = None
  result = run_ukri_job(log_id=log_id)
  return JSONResponse(result)


@app.post("/run/nihr")
async def run_nihr(request: Request):
  try:
    body = await request.json()
    log_id = body.get("log_id") if isinstance(body, dict) else None
  except:
    log_id = None
  result = run_nihr_job(log_id=log_id)
  return JSONResponse(result)


@app.post("/run/catapult")
async def run_catapult(request: Request):
  try:
    body = await request.json()
    log_id = body.get("log_id") if isinstance(body, dict) else None
  except:
    log_id = None
  result = run_catapult_job(log_id=log_id)
  return JSONResponse(result)
