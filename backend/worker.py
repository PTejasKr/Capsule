"""
Capsule Celery Worker
---------------------
Async task queue backed by Redis. Processes PR analysis and changelog
generation out-of-band so GitHub webhooks never block.

Broker  : redis://redis:6379/0   (Redis container in Docker network)
Backend : redis://redis:6379/1   (separate DB for task result storage)
"""
import os
import logging
from celery import Celery
from celery.signals import worker_ready
from backend.config import settings

logger = logging.getLogger("capsule.worker")

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
REDIS_HOST = getattr(settings, "REDIS_HOST", "redis")
REDIS_PORT = getattr(settings, "REDIS_PORT", 6379)

BROKER_URL   = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
BACKEND_URL  = f"redis://{REDIS_HOST}:{REDIS_PORT}/1"

celery_app = Celery(
    "capsule",
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=["backend.tasks"],  # auto-discover tasks module
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
import sys
IS_TESTING = os.environ.get("TESTING") == "true" or "pytest" in sys.modules

celery_app.conf.update(
    # Test setting
    task_always_eager=IS_TESTING,
    task_eager_propagates=IS_TESTING,

    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Reliability
    task_acks_late=True,           # Ack only after successful execution
    task_reject_on_worker_lost=True,

    worker_prefetch_multiplier=1,  # One task at a time per worker (LLM calls are heavy)

    # Result TTL — keep results for 2 hours (for webhook status polling)
    result_expires=7200,

    # Retry policy defaults (tasks can override)
    task_default_retry_delay=15,   # seconds
    task_max_retries=3,

    # Timezone
    timezone="UTC",
    enable_utc=True,
)

@worker_ready.connect
def on_worker_ready(**kwargs):
    logger.info("Capsule Celery worker is online and connected to Redis.")
