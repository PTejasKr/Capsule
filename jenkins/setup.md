# Capsule Jenkins Integration Setup Guide

Follow this guide to integrate Capsule with your Jenkins CI/CD server. This will enable automated code analysis when pull requests are created, and automated changelog publishing when they are merged.

## Prerequisites

1. **Jenkins Server**: Running Jenkins 2.346+ or higher.
2. **Capsule Backend**: The Capsule FastAPI service must be running and accessible from the Jenkins agent.
3. **GitHub Repository**: Admin access to configure webhooks.

## Step 1: Install Required Jenkins Plugins

Go to **Manage Jenkins** ➔ **Plugins** ➔ **Available Plugins** and install:

1. **Generic Webhook Trigger Plugin** (Enables parsing GitHub Webhook JSON payloads)
2. **HTTP Request Plugin** (Allows Jenkins to trigger Capsule API endpoints)
3. **GitHub Integration Plugin** (Standard pipeline integration)

*Restart Jenkins after installation if prompted.*

## Step 2: Configure API Key Credentials

1. Go to **Manage Jenkins** ➔ **Credentials** ➔ **System** ➔ **Global credentials**.
2. Click **Add Credentials**.
3. Select **Secret text** as the *Kind*.
4. Enter your Capsule `X-API-Key` (from your backend `.env` file) as the *Secret*.
5. Set the ID to `capsule-api-key`.
6. Add a description: `API Key for Capsule Extension and Webhook authentication`.
7. Click **Create**.

## Step 3: Create a Jenkins Pipeline Job

1. From the Jenkins dashboard, click **New Item**.
2. Enter the name: `capsule-pr-analyzer`.
3. Select **Pipeline** and click **OK**.
4. Scroll down to **Build Triggers** and check **Generic Webhook Trigger**.
5. Find the **Token** field and input: `capsule-pr-trigger`.
6. Under **Pipeline Definition**, select **Pipeline script from SCM**.
7. Select **Git** as SCM.
8. Enter your project's repository URL and authentication credentials.
9. Verify that **Script Path** is set to `jenkins/Jenkinsfile`.
10. Click **Save**.

## Step 4: Configure GitHub Webhook

To connect GitHub events to Jenkins:

1. Open your GitHub Repository and go to **Settings** ➔ **Webhooks**.
2. Click **Add webhook**.
3. Configure the following fields:
   - **Payload URL**: `http://<your-jenkins-server-domain>/generic-webhook-trigger/invoke?token=capsule-pr-trigger`
   - **Content type**: `application/json`
   - **Secret**: *(Leave blank or configure if using Generic Webhook HMAC validation)*
   - **Which events to trigger**: Select **Let me select individual events**.
     - Check **Pull requests**.
     - Uncheck everything else (e.g. *Pushes*).
   - Ensure **Active** is checked.
4. Click **Add webhook**.

*Note: If your Jenkins server is running locally behind a NAT/firewall, you must use a tool like **ngrok** to tunnel the webhook payload locally: `ngrok http 8080`.*

## Step 5: Verify Setup

1. Create a new branch in your GitHub repository.
2. Commit some modifications and open a **Pull Request** against `main`.
3. Verify that your Jenkins pipeline gets triggered automatically.
4. The pipeline will invoke the `/webhooks/jenkins` endpoint, completing the `Analyze Pull Request` stage.
5. In GitHub, check the side-panel Capsule widget or click the extension popup to view the summary.
6. Now, **Merge** the Pull Request.
7. Jenkins will execute the pipeline again. Since the PR is merged, it runs the `Publish Release Changelog` stage, prepending the release notes to `changelog.txt` in the release repository.
