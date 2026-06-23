class _Signal:
    def connect(self, func):
        # No-op decorator for signal handling in test environment
        return func

# Instantiate a dummy signal object
worker_ready = _Signal()
