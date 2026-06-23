from locust import HttpUser, task, between
import random
import json

class GitHubUser(HttpUser):
    wait_time = between(0.5, 1.5)
    host = "http://localhost:8000"

    @task(2)
    def webhook_open(self):
        payload = {
            "action": "opened",
            "number": random.randint(1000, 2000),
            "repository": {"full_name": "testorg/testrepo"},
            "pull_request": {"merged": False},
        }
        self.client.post(
            "/webhooks/github",
            json=payload,
            headers={"X-Github-Event": "pull_request"},
        )

    @task(1)
    def webhook_close(self):
        payload = {
            "action": "closed",
            "number": random.randint(1000, 2000),
            "repository": {"full_name": "testorg/testrepo"},
            "pull_request": {"merged": True},
        }
        self.client.post(
            "/webhooks/github",
            json=payload,
            headers={"X-Github-Event": "pull_request"},
        )

class JenkinsUser(HttpUser):
    wait_time = between(0.5, 1.5)
    host = "http://localhost:8000"

    @task
    def jenkins_trigger(self):
        payload = {
            "repo": "testorg/testrepo",
            "pr_number": random.randint(1000, 2000),
        }
        self.client.post(
            "/webhooks/jenkins",
            json=payload,
        )
