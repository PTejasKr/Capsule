import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

def make_request(url, method="GET", headers=None, payload=None):
    """Safely execute an HTTP request using urllib standard library."""
    if headers is None:
        headers = {}
    
    req_headers = {
        "Accept": "application/json",
    }
    req_headers.update(headers)
    
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
        
    # Security: only allow https:// requests to prevent file:// or custom scheme abuse (B310)
    if not url.startswith("https://"):
        return 400, {"detail": f"Blocked request to non-HTTPS URL: {url}"}

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:  # nosec B310 — URL scheme validated above
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_data = {"detail": e.reason}
        return e.code, err_data
    except Exception as e:
        return 500, {"detail": str(e)}

def post_github_comment(repo, pr_number, token, body):
    """Post a comment on the GitHub pull request."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Capsule-CI-Helper"
    }
    payload = {"body": body}
    status, res = make_request(url, method="POST", headers=headers, payload=payload)
    if status == 201:
        print("Successfully posted PR comment to GitHub.")
    else:
        print(f"Warning: Failed to post GitHub comment. Status: {status}, Detail: {res.get('detail')}")

def run_analysis(args):
    api_url = args.api_url or os.environ.get("CAPSULE_API_URL", "http://localhost:8000")
    api_key = args.api_key or os.environ.get("CAPSULE_API_KEY")
    github_token = args.github_token or os.environ.get("GITHUB_TOKEN")
    
    if not api_key:
        print("Error: Capsule API Key is required. Set CAPSULE_API_KEY environment variable or pass --api-key.")
        sys.exit(1)
        
    print(f"Triggering Capsule PR analysis for {args.repo} PR #{args.pr}...")
    trigger_url = f"{api_url}/webhooks/jenkins"
    headers = {"X-API-Key": api_key}
    payload = {
        "pr_number": int(args.pr),
        "repo": args.repo
    }
    
    status, response = make_request(trigger_url, method="POST", headers=headers, payload=payload)
    
    if status not in (200, 202):
        print(f"Error: Failed to trigger analysis. Status: {status}, Detail: {response.get('detail')}")
        sys.exit(1)
        
    analysis_result = None
    if status == 200:
        # Sync response
        print("Analysis completed synchronously.")
        analysis_result = response.get("summary")
    else:
        # Async response
        task_id = response.get("task_id")
        print(f"Analysis enqueued. Task ID: {task_id}. Polling for completion...")
        
        poll_url = f"{api_url}/webhooks/task/{task_id}"
        max_attempts = 60 # 5 minutes max
        attempt = 0
        
        while attempt < max_attempts:
            time.sleep(5)
            attempt += 1
            p_status, p_resp = make_request(poll_url, headers=headers)
            
            if p_status != 200:
                print(f"Error: Failed to poll task. Status: {p_status}, Detail: {p_resp.get('detail')}")
                sys.exit(1)
                
            state = p_resp.get("state")
            print(f"[{attempt}] Task state: {state}")
            
            if state == "SUCCESS":
                analysis_result = p_resp.get("result", {}).get("data")
                break
            elif state == "FAILURE":
                print(f"Error: PR analysis task failed. Detail: {p_resp.get('error')}")
                sys.exit(1)
                
        if not analysis_result:
            print("Error: Polling timed out before task completed.")
            sys.exit(1)
            
    # Print analysis summary
    print("\n" + "="*80)
    print(f" CAPSULE ANALYSIS FOR PR #{args.pr}")
    print("="*80)
    print(f"Title:      {analysis_result.get('title')}")
    print(f"Confidence: {int(analysis_result.get('confidence_score', 0) * 100)}%")
    
    wf_impact = analysis_result.get("workflow_impact", {})
    severity = wf_impact.get("severity", "none").upper()
    has_impact = wf_impact.get("has_impact", False)
    
    print(f"Workflow Impact: {'YES' if has_impact else 'NO'} (Severity: {severity})")
    print(f"Description:     {wf_impact.get('impact_description', 'N/A')}")
    print(f"Affected Flows:  {', '.join(wf_impact.get('affected_workflows', [])) or 'None'}")
    print("-"*80)
    print("Summary:")
    print(analysis_result.get("summary"))
    print("="*80 + "\n")
    
    # Format a Markdown summary for the GitHub PR Comment
    comment_body = f"""### 🛡️ Capsule CI Analysis Report
**Pull Request:** #{args.pr}
**Title:** {analysis_result.get('title')}
**Confidence Score:** `{int(analysis_result.get('confidence_score', 0) * 100)}%`

#### 📊 Workflow Impact Assessment
- **Has Workflow Impact:** {'Yes' if has_impact else 'No'}
- **Change Severity:** `{severity}`
- **Affected Business Flows:** {', '.join([f'`{f}`' for f in wf_impact.get('affected_workflows', [])]) or 'None'}

> **Description:** {wf_impact.get('impact_description', 'No impact details.')}

<details>
<summary><b>🔍 View AI Summary Details</b></summary>

{analysis_result.get('summary')}

</details>

*Automated by Capsule Enterprise Pipeline.*
"""

    if github_token:
        post_github_comment(args.repo, args.pr, github_token, comment_body)
        
    # Check if the PR requires approval
    if has_impact and severity == "MAJOR":
        # Check if already approved
        print("Checking if PR is already approved in the Capsule database...")
        check_url = f"{api_url}/api/pr/{args.pr}/summary?repo={urllib.parse.quote(args.repo)}"
        c_status, c_resp = make_request(check_url, headers=headers)
        
        if c_status == 403:
            print("❌ CRITICAL: PR contains MAJOR workflow changes and is NOT approved.")
            print("Please ask an administrator to review and approve the PR using the Chrome Extension or by sending a POST request to '/api/pr/{pr_number}/approve'.")
            sys.exit(1)
        elif c_status == 200:
            print("✅ PR contains MAJOR workflow changes but has been APPROVED by an administrator. CI check passed.")
            sys.exit(0)
        else:
            print(f"Warning: Failed to fetch approval status (Status: {c_status}). Assuming NOT approved.")
            sys.exit(1)
    else:
        print("✅ PR has no major workflow deviations. CI check passed.")
        sys.exit(0)

def run_merge(args):
    api_url = args.api_url or os.environ.get("CAPSULE_API_URL", "http://localhost:8000")
    api_key = args.api_key or os.environ.get("CAPSULE_API_KEY")
    
    if not api_key:
        print("Error: Capsule API Key is required for merge changelog publishing.")
        sys.exit(1)
        
    print(f"Publishing release changelog for merged PR #{args.pr}...")
    merge_url = f"{api_url}/api/pr/{args.pr}/generate-changelog?repo={urllib.parse.quote(args.repo)}"
    headers = {"X-API-Key": api_key}
    
    status, response = make_request(merge_url, method="POST", headers=headers)
    
    if status == 200:
        print(f"✅ Success: Changelog generated and pushed to release branch!")
        print(f"Version Released: {response.get('version')}")
    else:
        print(f"❌ Error: Failed to publish changelog. Status: {status}, Detail: {response.get('detail')}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Capsule Enterprise CI/CD Pipeline Helper")
    parser.add_argument("--action", required=True, choices=["analyze", "merge"], help="Pipeline action to execute")
    parser.add_argument("--repo", required=True, help="Repository in owner/repo format")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number")
    parser.add_argument("--api-url", help="Capsule API base URL")
    parser.add_argument("--api-key", help="Capsule API authentication key")
    parser.add_argument("--github-token", help="GitHub Personal Access Token / GITHUB_TOKEN")
    
    args = parser.parse_args()
    
    if args.action == "analyze":
        run_analysis(args)
    elif args.action == "merge":
        run_merge(args)

if __name__ == "__main__":
    main()
