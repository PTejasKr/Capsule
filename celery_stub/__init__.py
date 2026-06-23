# Minimal stub for Celery used in integration tests

class Celery:
    def __init__(self, *args, **kwargs):
        # Simple placeholder for Celery configuration
        self.conf = {}
        pass

    def task(self, *args, **kwargs):
        # Decorator that returns the original function unchanged
        def decorator(func):
            return func
        return decorator
