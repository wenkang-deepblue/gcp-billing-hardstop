# GCP Billing Hardstop

This project provides an automated "Hard Stop" mechanism for Google Cloud Platform (GCP). It enhances the official GCP "Disable billing with budget notifications" approach. While it cannot guarantee absolutely zero overspend, it **maximizes your financial protection by automatically pulling the plug when a budget threshold is reached.**

Reference: [Disable billing usage with notifications](https://cloud.google.com/billing/docs/how-to/disable-billing-with-notifications#functions_cap_billing_dependencies-python)

## Background

In the era of cloud computing and AI, developers face increasingly complex risks of runaway bills. This project is built to mitigate those risks.

### Why this project exists
For solo developers and small teams, a **"Hard Stop" (absolute spending limit)** is not just a nice-to-have; it's a vital self-defense mechanism. 
There are countless horror stories of developers waking up to massive bills because an API key was accidentally pushed to GitHub or exposed in frontend code. While GCP provides Budget Alerts, they are **only notifications**. If a malicious actor exploits your key while you are asleep, thousands of dollars could be spent before you even see the email. We need an **automated, forceful circuit breaker**, not just an alarm.

### The New Threat: Runaway AI Agents
Beyond traditional key leaks, the AI boom introduces a brand new threat vector. 
Autonomous AI agents (such as OpenClaw, AutoGPT, etc.) are granted the ability to call LLM APIs continuously. If an agent encounters a logic bug, falls into an infinite loop, or hallucinates, it can uncontrollably consume massive amounts of tokens in minutes.
In this "autonomous rampage" scenario, even if your API key is perfectly secure, your own program could drain your wallet instantly due to extreme concurrency.

### How this project stops the bleeding
GCP does not offer a native "shut down when funds are exhausted" toggle. However, we can build a "physical billing cut-off" programmatically.
The core logic is:
1. **Monitor Spend:** Use GCP Cloud Billing Budgets to monitor costs in real-time. When it hits 100% of your defined threshold, it emits a Pub/Sub message.
2. **Trigger Action:** The over-budget message triggers a serverless function (Cloud Run Functions).
3. **Pull the Plug:** The function calls the Cloud Billing API to **forcefully unlink your project from its Billing Account**.

This is akin to "sawing off the branch you're sitting on": once unlinked, GCP will automatically shut down all paid resources in that project—including the very function that just executed the shutdown. Through this brutal but effective method, even in the worst-case scenario of a leak or an AI agent going rogue, your maximum financial loss is strictly capped near your predefined budget.

## Architecture Overview

The solution consists of three components:

1. **Cloud Billing Budget**: Monitors the cost and sends a programmatic notification when the threshold is reached.
2. **Pub/Sub Topic**: Receives and forwards the budget notification.
3. **Cloud Run Functions** (formerly Cloud Functions Gen2): Triggers the `stop_billing()` function in `main.py`, calling the Cloud Billing API to unlink the billing account from the project.

**Once unlinked successfully, all paid resources within the project will be gradually shut down, including this function itself.**

## Key Enhancements in This Project

Compared to the official GCP example, `main.py` in this repository includes several robustness enhancements:

1. **Reliable Project Identification**: Searches for the target project ID in the order of `TARGET_PROJECT_ID` -> `GCP_PROJECT` -> `GOOGLE_CLOUD_PROJECT` -> Metadata Server.
2. **Strict Message Validation**: Validates required fields and safely parses amounts using `Decimal` to avoid type errors or dirty data execution.
3. **Idempotency Checks**: Verifies if billing is already disabled before attempting to unlink, preventing redundant API calls.
4. **Optional Budget Isolation**: Uses `EXPECTED_BUDGET_NAME` to ensure the function only reacts to specific budget alerts, reducing the risk of misfires.
5. **Enterprise-Grade Observability**: Utilizes JSON structured logging for better tracing in Cloud Logging.
6. **Explicit Error Handling**: Raises exceptions on critical failures rather than silently failing, allowing the platform to recognize the failure and trigger retries.

## Important Limitations

While highly effective, you must understand the natural boundaries of this mechanism:

1. **It is NOT a Real-Time Hard Gate**: Budget notifications have an inherent delay. Therefore, it cannot guarantee the project will shut down at *exactly* the defined dollar amount. [GCP documentation](https://cloud.google.com/billing/docs/how-to/disable-billing-with-notifications#functions_cap_billing_dependencies-python) explicitly states this.
2. **It is a Destructive Action**: Unlinking a billing account affects ALL services in the project, including Free Tier services and this function itself.
3. **It Does NOT Replace Key Governance**: API key restrictions, IAM minimum privilege, and quotas are still your first line of defense.

**Best Practice:** Set your budget amount **LOWER** than the maximum loss you can tolerate to leave a buffer for billing delays.

## Prerequisites

According to GCP documentation: *"You can't disable billing on a project that's locked to a billing account."*
Please verify that your project is not locked to a billing account:

Navigation path: Hamburger menu (or search `billing` in the top search bar) -> `Billing` -> `Account Management` -> Click the three dots under `Actions` on the right side of your project. If `Lock billing` is NOT grayed out, your project is not locked. If it is locked, you must unlock it first (Requires `Billing Account Administrator` permissions, and sometimes `Organization Administrator`).

![billing_unlocking](/snapshots/billing_unlocking.png)

## Step 1: Enable Necessary APIs

Open the **Cloud Shell** (the terminal icon `>_` at the top right of the GCP Console).
Execute the following command (unless specified otherwise, run all commands in this guide in Cloud Shell):

```bash
gcloud services enable billingbudgets.googleapis.com \
    pubsub.googleapis.com \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    cloudbilling.googleapis.com
```

## Step 2: Create a Pub/Sub Topic

It is recommended to use one dedicated Pub/Sub topic per budget to minimize misfire risks.

```bash
gcloud pubsub topics create billing-alerts
```

## Step 3: Prepare the Code Directory

- In Cloud Shell, create a directory and enter it:

    ```bash
    mkdir billing-killer && cd billing-killer
    ```

- Create the `requirements.txt` file:

    ```bash
    nano requirements.txt
    ```
    Copy and paste the content from `requirements.txt` in this repository. Press `Ctrl+O` to save, `Enter` to confirm, and `Ctrl+X` to exit.

## Step 4: Prepare `main.py`

- Create the `main.py` file:
    ```bash
    nano main.py
    ```
    Copy and paste the content from `main.py` in this repository. Press `Ctrl+O` to save, `Enter` to confirm, and `Ctrl+X` to exit.

- The function supports the following environment variables (see the **Appendix** for how to manage them):

    ### Required
    1. `TARGET_PROJECT_ID`: Explicitly specify the Project ID to protect.

    ### Testing (Crucial for first deployment)
    2. `SIMULATE_DEACTIVATION`: Whether to simulate the action without actually disabling billing.
       - `true`: Only logs the intent, does not unlink billing. (Enable this first)
       - `false`: Physically unlinks the billing account upon triggering.

    ### Optional but Recommended
    3. `EXPECTED_BUDGET_NAME`: Only accept notifications from a specific budget name. This value is the **Cloud Billing Budget Name** (see Step 5), NOT the Pub/Sub topic name.

       *Example:*
       - Budget Name: `Hard-Stop-Budget`
       - Pub/Sub Topic Name: `billing-alerts`
       - Variable Setup: You set `EXPECTED_BUDGET_NAME=Hard-Stop-Budget` and connect this budget to the `billing-alerts` topic.

## Step 5: Create Budget Alerts

Perform these steps in the GCP Console UI:

Navigation path: Hamburger menu -> `Billing` -> `Budgets & alerts` -> `Create budget`

1. **Name**: Enter your budget name. **NOTE:** This exact name (case-sensitive) must be used in Step 7 for `EXPECTED_BUDGET_NAME`. Example: `Hard-Stop-Budget`.
2. **Time range**: Select as needed, typically `Monthly`.
3. **Projects**: Select the project you want to protect.
4. **Services**: Leave as default (All services).
5. **Savings / Credits**: **ATTENTION:** If you have free credits, it is recommended **NOT** to check `Free tier credits` and `Promotional credits`. 
   - *If checked:* The alert calculates `(Actual Cost) - (Credits)`. If you set the threshold to $100 and have $300 in credits, the killswitch will only trigger when you have burned through all $300 credits PLUS $100 in actual cash.
   - *If unchecked:* The alert triggers purely on usage value. It will trigger at $100 usage, which is completely covered by your credits, saving you from spending real money.
6. **Amount**: Set your threshold based on your actual needs. Recommended to be **less than your maximum acceptable loss**.
7. **Actions**: Check `Connect a Pub/Sub topic to this budget` and select the topic created in Step 2: `billing-alerts`.
8. Click **Finish**.

## Step 6: Grant Permissions to the Default Service Account

Before granting permissions, get your `Project number` from the GCP Console Home dashboard:

![Project number](/snapshots/project_number.png)

**Note:** Replace `XXXXXXXXXXX` with your `Project number`, and `YOUR_PROJECT_ID` with your `Project ID` in the commands below.

### 1. Grant `cloudbuild.builds.builder` role
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
 --member=serviceAccount:XXXXXXXXXXX-compute@developer.gserviceaccount.com \
 --role=roles/cloudbuild.builds.builder 
```

### 2. Grant Pub/Sub Service Account the "Token Creator" role
Pub/Sub needs to generate an identity token. Run the following command:
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:service-XXXXXXXXXXX@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountTokenCreator"
```

### 3. Grant the trigger permission to invoke Cloud Run
```bash
gcloud run services add-iam-policy-binding billing-killer \
    --region=us-central1 \
    --member="serviceAccount:XXXXXXXXXXX-compute@developer.gserviceaccount.com" \
    --role="roles/run.invoker"
```

### 4. Grant `Billing Account Administrator` role
This is required for the function to physically detach the billing account.
Navigation path: Hamburger menu -> `Billing` -> `Account Management` -> Right sidebar `Add principal` -> Enter your service account `XXXXXXXXXXX-compute@developer.gserviceaccount.com` -> Select role `Billing Account Administrator` -> `Save`.

![billing_management](/snapshots/billing_management.png)

## Step 7: Deploy to Cloud Run Functions

**Note:** Replace `YOUR_PROJECT_ID` below with your actual Project ID.

For the initial deployment, **do not enable real deactivation**. Deploy with `SIMULATE_DEACTIVATION=true` to verify the message pipeline, permissions, and logs.

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --runtime python312 \
    --region us-central1 \
    --retry \
    --trigger-topic billing-alerts \
    --entry-point stop_billing \
    --set-env-vars TARGET_PROJECT_ID=YOUR_PROJECT_ID,SIMULATE_DEACTIVATION=true,EXPECTED_BUDGET_NAME=Hard-Stop-Budget
```

*Note: If prompted `API [eventarc.googleapis.com] not enabled`, enter `y` to confirm.*

## Step 8: Validate in Simulation Mode

Verify that the notification reaches the function and is parsed correctly without causing real downtime.

1. Keep `SIMULATE_DEACTIVATION=true`.
2. Go to `Pub/Sub` to send a mock budget alert:
   Navigation path: Hamburger menu -> `Pub/Sub` -> `Topics` -> Click `billing-alerts` -> `Messages` -> `Publish Message`.

   ![pub/sub](/snapshots/pub_sub.png)

   Copy-paste the JSON below into the `Message Body`. 
   *Replace `YOUR_BUDGET_AMOUNT` with your threshold (e.g., 100) and `YOUR_COST_AMOUNT` with a value slightly higher (e.g., 100.5).*

   ```json
   {
       "budgetDisplayName": "Hard-Stop-Budget",
       "costAmount": YOUR_COST_AMOUNT,
       "costIntervalStart": "2026-03-01T00:00:00Z",
       "budgetAmount": YOUR_BUDGET_AMOUNT,
       "budgetAmountType": "SPECIFIED_AMOUNT",
       "currencyCode": "USD"
   }
   ```
   ![simulation_message](/snapshots/simulation_message.png)

3. Check the logs in Cloud Run:
   Navigation path: Hamburger menu -> `Cloud Run` -> Click `billing-killer` -> `Logs`.
   You should see logs indicating:
   - Received budget notification
   - Budget threshold reached
   - Simulation mode enabled. Billing disable skipped.

   ![cloud_run_logs](/snapshots/cloud_run_logs.png)

   If these logs appear, your Pub/Sub-to-Function pipeline and environment variables are correctly configured.

## Step 9: Switch to Real Deactivation Mode

Once simulation is successful, deploy again with `SIMULATE_DEACTIVATION=false`. This will overwrite the simulation version.

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --runtime python312 \
    --region us-central1 \
    --retry \
    --trigger-topic billing-alerts \
    --entry-point stop_billing \
    --set-env-vars TARGET_PROJECT_ID=YOUR_PROJECT_ID,SIMULATE_DEACTIVATION=false,EXPECTED_BUDGET_NAME=Hard-Stop-Budget
```

## Step 10: Post-Deployment Checklist

- [ ] Is the function deployed in the correct project?
- [ ] Does `TARGET_PROJECT_ID` match the project you want to protect?
- [ ] Does `EXPECTED_BUDGET_NAME` exactly match the name in the Budgets UI?
- [ ] Are there any persistent permission errors in the Cloud Run logs?
- [ ] **Highly Recommended:** Create a brand new, empty test project. Set the budget to $1, and execute a live drill to ensure it unlinks the billing account successfully.

## Expected Behavior on Trigger

When the killswitch successfully triggers:
1. The target project is unlinked from the billing account.
2. All paid resources inside the project begin to shut down.
3. The `billing-killer` function itself will eventually become unavailable.
4. **Recovery:** You must manually re-link the billing account and restart your services via the GCP Console.

## Common Causes of Failure

If the killswitch fails to stop billing, check the following:
1. `SIMULATE_DEACTIVATION` is still set to `true`.
2. The service account lacks the `Billing Account Administrator` role.
3. The project has a `Billing Lock` applied.
4. `EXPECTED_BUDGET_NAME` has a typo.
5. The budget notification hasn't been emitted yet by GCP (inherent delay).
6. The function was deployed without the `--retry` flag, dropping the event on a temporary failure.

## Final Reminders & Multi-Layer Defense

This solution is an extremely effective **"Ultimate Circuit Breaker"** and **"Post-Incident Damage Control"** mechanism, but **you should never rely on it as your ONLY line of defense.** 
Because GCP budget calculations naturally have latency, there is a window (minutes to hours) between the overspend occurring and the plug being pulled.

To truly minimize risk, combine this killswitch with the following **Proactive Defenses**:

1. **Set API Quotas (Crucial for AI Agent Rampage)**:
   In the GCP `Quotas` page, set hard caps on Requests Per Minute (RPM) and Tokens Per Day (TPD) for LLM APIs (like Gemini). If an autonomous agent enters an infinite loop, it will be blocked by the API gateway before it can rack up a massive bill.
2. **Restrict API Keys by Origin**:
   Lock your API keys to specific IP addresses, referrers (domains), or iOS/Android bundle IDs.
3. **Restrict API Keys by Service**:
   Limit the key so it can ONLY call specific APIs (e.g., restrict to Gemini API, blocking it from spinning up Compute Engine instances).
4. **Principle of Least Privilege (PoLP)**:
   Never grant `Owner` or `Editor` roles to service accounts out of convenience. Grant only the exact permissions needed for the task.
5. **Environment Isolation**:
   Keep experiments, unstable AI agents, and production workloads in separate GCP projects. Attach this killswitch to your experimental projects with a very low budget.

## Appendix: Managing Environment Variables

*(Assuming function name `billing-killer` and region `us-central1`. Adjust if yours differ.)*

### View Current Variables
```bash
gcloud functions describe billing-killer --gen2 --region us-central1
```

### Update a Single Variable
```bash
gcloud functions deploy billing-killer --gen2 --region us-central1 \
    --update-env-vars SIMULATE_DEACTIVATION=false
```

### Remove a Variable
```bash
gcloud functions deploy billing-killer --gen2 --region us-central1 \
    --remove-env-vars EXPECTED_BUDGET_NAME
```

### Clear All Variables
```bash
gcloud functions deploy billing-killer --gen2 --region us-central1 --clear-env-vars
```
