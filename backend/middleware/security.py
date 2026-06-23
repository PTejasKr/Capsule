import hmac
import hashlib
import logging
import re
from fastapi import Request, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from backend.config import settings

logger = logging.getLogger("capsule.security")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if not api_key or api_key != settings.API_KEY:
        logger.warning("Invalid or missing API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )
    return api_key

async def verify_github_signature(request: Request):
    if not settings.GITHUB_WEBHOOK_SECRET:
        # If secret is not configured, skip verification (log a warning in production)
        logger.warning("GitHub webhook secret is not set. Skipping verification.")
        return

    signature_header = request.headers.get("x-hub-signature-256")
    if not signature_header:
        logger.error("Missing x-hub-signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing signature"
        )

    # Payload must be read as raw bytes to calculate signature
    body = await request.body()
    
    # Check signature
    sha_name, signature = signature_header.split("=")
    if sha_name != "sha256":
        logger.error("Signature algorithm is not sha256")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Hash algorithm not supported"
        )

    mac = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        msg=body,
        digestmod=hashlib.sha256
    )
    
    if not hmac.compare_digest(mac.hexdigest(), signature):
        logger.error("Signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )

def sanitize_text(text: str) -> str:
    """
    Sanitizes input text to protect against prompt injection and homoglyph attacks.
    """
    if not text:
        return ""
    
    # 1. Block common prompt injection phrases by neutralising them
    injection_patterns = [
        r"(?i)ignore\s+(?:all\s+)?previous\s+instructions",
        r"(?i)system\s*:\s*",
        r"(?i)you\s+are\s+now\s+a\s+",
        r"(?i)forget\s+everything",
        r"(?i)bypass\s+guardrails",
        r"(?i)new\s+rule\s*:"
    ]
    
    sanitized = text
    for pattern in injection_patterns:
        sanitized = re.sub(pattern, "[CLEANED INJECTION ATTEMPT]", sanitized)
        
    # 2. Prevent Base64 encoded payload attacks in code diffs or PR text
    # (Matches long strings of letters/numbers ending in = or ==)
    base64_pattern = r"(?:[A-Za-z0-9+/]{4}){10,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?"
    sanitized = re.sub(base64_pattern, "[REMOVED POTENTIAL BASE64 PAYLOAD]", sanitized)
    
    # 3. Unicode Homoglyph Attack prevention
    # We normalize any weird characters or replace non-standard lookalikes if needed.
    # For simplicity, we filter out characters outside standard ASCII / UTF-8 code blocks 
    # that are commonly used to mimic standard text (like cyrillic lookalikes).
    # Specifically, look for characters in the cyrillic or mathematical alphanumeric range.
    # We will log if suspicious unicode sequences are detected.
    suspicious_chars = re.compile(r"[\u0400-\u04FF\u0500-\u052F\u2100-\u214F\U0001D400-\U0001D7FF]")
    if suspicious_chars.search(sanitized):
        logger.warning("Detected potential unicode homoglyph character. Sanitizing to ASCII equivalents.")
        # Replace cyrillic lookalikes with standard ascii if needed, or simply strip suspicious blocks
        sanitized = suspicious_chars.sub("[REMOVED HOMOGLYPH]", sanitized)
        
    return sanitized
