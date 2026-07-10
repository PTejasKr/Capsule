
class Celery:
    def __init__(self, *args, **kwargs):
        self.conf = {}
        pass

    def task(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator
