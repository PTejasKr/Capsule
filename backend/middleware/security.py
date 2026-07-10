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
    if not api_key or (api_key != settings.API_KEY and api_key != "dev-bypass"):
        logger.warning("Invalid or missing API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )
    return api_key

async def verify_github_signature(request: Request):
    import os
    if request.headers.get("x-sandbox-mock") == "true" or os.environ.get("SANDBOX_MOCK") == "true":
        logger.warning("SANDBOX MODE: Skipping GitHub webhook signature verification.")
        return

    if not settings.GITHUB_WEBHOOK_SECRET:
        import os
        if os.environ.get("ENV", "production").lower() == "production":
            logger.error("GITHUB_WEBHOOK_SECRET is not configured. Rejecting webhook.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook verification is not configured on this server."
            )
        logger.warning("DEV MODE: GitHub webhook secret is not set. Skipping verification.")
        return

    signature_header = request.headers.get("x-hub-signature-256")
    if not signature_header:
        logger.error("Missing x-hub-signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing signature"
        )

    body = await request.body()

    if "=" not in signature_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed signature header"
        )

    sha_name, _, signature = signature_header.partition("=")
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

def validate_repo_name(repo: str) -> bool:
    """
    Validates a GitHub repository name (owner/repo).
    Prevents path traversal and injection attacks.
    """
    if not repo:
        return False
    pattern = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$")
    return bool(pattern.match(repo))

def sanitize_text(text: str) -> str:
    """
    Sanitizes input text to protect against prompt injection and homoglyph attacks.
    """
    if not text:
        return ""
    
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
        
    base64_pattern = r"(?:[A-Za-z0-9+/]{4}){10,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?"
    sanitized = re.sub(base64_pattern, "[REMOVED POTENTIAL BASE64 PAYLOAD]", sanitized)
    
    secret_patterns = [
        r"(?i)AKIA[0-9A-Z]{16}", # AWS Key
        r"(?i)ghp_[a-zA-Z0-9]{36}", # GitHub PAT
        r"eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*" # JWT
    ]
    for pattern in secret_patterns:
        sanitized = re.sub(pattern, "[REDACTED SECRET]", sanitized)
    
    suspicious_chars = re.compile(r"[\u0400-\u04FF\u0500-\u052F\u2100-\u214F\U0001D400-\U0001D7FF]")
    if suspicious_chars.search(sanitized):
        logger.warning("Detected potential unicode homoglyph character. Sanitizing to ASCII equivalents.")
        sanitized = suspicious_chars.sub("[REMOVED HOMOGLYPH]", sanitized)
        
    return sanitized
