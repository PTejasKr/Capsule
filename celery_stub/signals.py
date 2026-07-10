class _Signal:
    def connect(self, func):
        return func

worker_ready = _Signal()
