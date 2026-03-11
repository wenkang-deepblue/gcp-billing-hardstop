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

## Below is Chinese Version
## 以下为中文版

# GCP Billing Hardstop 部署说明

这份文档对应当前仓库里的加固版 `main.py`。  
它基于 Google 官方“预算通知触发后自动停用 billing”的思路做了增强，目标不是“绝对零超支”，而是**在预算通知到达后，尽最大限度自动止损**。

参考官方文档：
- [Disable billing usage with notifications](https://docs.cloud.google.com/billing/docs/how-to/disable-billing-with-notifications#functions_cap_billing_dependencies-python)

## 背景

在云服务和 AI 时代，开发者面临着更加复杂的账单失控风险。这个项目（GCP Billing Hardstop）正是为了应对这些风险而生。

### 为什么会有这个项目 (Why)
对于个人开发者或小团队来说，**“绝对硬性上限”（Hard Stop）**不仅是合理的，更是不可或缺的“防身手段”。

在互联网上，因为 API Key 意外泄漏到 GitHub 或前端代码中，导致黑客恶意盗刷，让受害者一觉醒来“天塌了”、“房子归云平台了”的新闻屡见不鲜。

虽然 GCP 官方提供了预算提醒（Budget Alerts），但它**只是通知**。想象一下，如果恶意盗刷发生在你深夜熟睡时，就算邮箱里收到了无数封超支报警，你也根本来不及处理。等你看到邮件时，账单可能已经飙升到了上万美元。我们需要的是**自动化的强制熔断机制**，而不是单纯的提醒。

### 意料之外的新风险：失控的 AI Agent (What)
除了传统的密钥被盗，如今我们还面临着一个全新的威胁场景。

随着 AI 技术的爆发，各种全自动的 AI Agent（例如近期大火的 OpenClaw、AutoGPT 等）被广泛使用。这些 Agent 被赋予了自主调用大模型 API 的能力。如果由于逻辑 Bug、死循环，或者模型自身的幻觉，导致 Agent 进入了“疯狂调用”状态，它会在极短的时间内不受控制地消耗海量 Token。

在这种“自主狂暴”的情况下，即便你的密钥没有泄露给任何人，你自己运行的程序也会因为极高的请求并发量，瞬间将你的钱包榨干。

### 本项目如何为你止损 (How)
GCP 本身并没有直接提供“余额用尽自动关机”的开关，但我们可以通过编程方式自己实现一个“账单物理切断器”。

本项目的核心逻辑是：
1. **监听费用**：利用 GCP 的预算提醒（Budgets）实时监控成本，并在达到 100% 阈值时触发一条 Pub/Sub 消息。

2. **强制解绑**：收到超支消息后，立即触发无服务器函数（Cloud Run Functions）。

3. **物理拔线**：该函数通过调用 Cloud Billing API，**直接将当前项目与其绑定的信用卡/结算账号（Billing Account）强制解绑**。

这就好比“坐在树枝上锯树枝”：一旦解绑成功，GCP 会自动关停该项目下的所有付费资源（包括刚刚立下大功的这个停用程序本身）。通过这种“暴力但有效”的方式，即使出现最极端的盗刷或 Agent 暴走，你的最大经济损失也会被严格限制在设定的预算金额附近。

## 方案概览

整套方案由三部分组成：

1. `Cloud Billing Budget`
   当费用达到阈值时，发出程序化通知。

2. `Pub/Sub Topic`
   负责接收并转发预算通知。

3. `Cloud Run Functions` (原 `Cloud Functions Gen2`)
   触发 `main.py` 中的 `stop_billing()`，调用 Cloud Billing API 解除项目与 billing account 的绑定。

**一旦解绑成功，项目中的付费资源会被陆续停掉，包括这个函数自己。**

## 本项目代码相比官方示例的加固点

当前 `main.py` 在官方思路基础上做了以下增强：

1. 更稳地确定要保护的项目
   支持按 `TARGET_PROJECT_ID` --> `GCP_PROJECT` --> `GOOGLE_CLOUD_PROJECT` --> metadata server 的顺序查找目标项目。

2. 更严格地校验预算消息
   会检查必要字段，并用 `Decimal` 比较金额，避免脏数据或类型问题导致误判。

3. 更接近幂等
   在真正解绑前，会先查询当前项目 billing 是否已经关闭。

4. 可选的预算隔离
   可通过 `EXPECTED_BUDGET_NAME` 只接受指定预算名的通知，降低误触发风险。

5. 更好的失败可见性
   使用结构化日志输出关键信息。

6. 失败时显式抛错
   不再只是打印错误后悄悄返回，便于平台识别此次执行失败。

## 重要限制

这套机制虽然有用，但必须接受它的天然边界：

1. 它不是实时硬闸门

    预算通知本身存在延迟，所以不能保证“恰好到 X 美元时立刻停机”。[Google 官方文档](https://docs.cloud.google.com/billing/docs/how-to/disable-billing-with-notifications#functions_cap_billing_dependencies-python)也明确写了这一点。

2. 它是暴力止损

    一旦解绑 billing，项目内所有付费服务都会受到影响，包括免费层级服务和当前函数本身。

3. 它无法替代密钥治理

    API key 的来源限制、API 限制、服务账号最小权限、配额限制，仍然是第一道防线。

实践建议：预算金额**不要等于**你能承受的最大损失，应当**低于**那个数字，给账单延迟留缓冲。

## 必要确认

根据 GCP 官方文档，“You can't disable billing on a project that's locked to a billing account”。请到 `Billing` 中查看你的项目是否被锁定到了结算账号：

操作路径：左上角三条横线  (或直接在顶部搜索框中搜索 `billing`)  --> `Billing` --> `Account Management` --> 点击你的项目右侧 `Actions` 下方的三个圆点，出现的菜单中，如果 `Lock billing` 不是灰色，表示你的项目未被锁定，反之则是已被锁定，你要先解除锁定 (请自行搜索解除锁定的方法。你需要 `Billing Account Administrator` 权限才可以，某些情况下，还需要 `Organization Administrator` 权限，这里不展开了)

![billing_unlocking](/snapshots/billing_unlocking.png)

## 第 1 步：启用必要 API

在目标项目里打开 Cloud Shell ( GCP 控制台页面右上角命令行图标)

![cloud_shell](/snapshots/cloud_shell.png)

在 Cloud Shell 中执行 (如无特别说明，本文档中所有命令都请在 Cloud Shell 中执行)：

```bash
gcloud services enable billingbudgets.googleapis.com \
    pubsub.googleapis.com \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    cloudbilling.googleapis.com
```

## 第 2 步：创建 Pub/Sub 主题

建议一个预算对应一个独立 Pub/Sub topic，减少误触发概率。

```bash
gcloud pubsub topics create billing-alerts
```

## 第 3 步：准备代码目录

- 在 Cloud Shell 里手工部署：

    ```bash
    mkdir billing-killer && cd billing-killer
    ```

- 创建`requirements.txt`文件：

    ```bash
    nano requirements.txt
    ```
    将本仓库中的`requirements.txt`中的内容完整 copy-paste 进去，然后按 `Ctrl+O` 保存，`Enter` 确认，`Ctrl+X` 退出

## 第 4 步：确认 `main.py`

- 创建`main.py`文件：
    ```bash
    nano main.py
    ```
    将本仓库中的`main.py`中的内容完整copy-paste进去，然后按 `Ctrl+O` 保存，`Enter` 确认，`Ctrl+X` 退出

- 支持以下环境变量 (使用环境变量方法见文档末尾**附录**章节)：

    ### 必填

    1. `TARGET_PROJECT_ID`
    显式指定要保护的项目 ID 。

    ### `SIMULATE_DEACTIVATION` 建议先打开 `true`、测试完成后关闭 `false`

    2. `SIMULATE_DEACTIVATION`
    是否只模拟、不真实停用 billing。
    - `true`：只打日志，不解绑 billing
    - `false`：达到条件后真实解绑 billing

    ### 可选但推荐

    3. `EXPECTED_BUDGET_NAME`
        只接受指定预算名称发来的通知。这里的值是 **Cloud Billing Budget 的名称** (见**第5步**)，不是 Pub/Sub topic 名。  

        举例说明：

        1. 预算名称可以叫 `Hard-Stop-Budget`

        2. Pub/Sub topic 名可以叫 `billing-alerts`

        3. 两者是不同层级的对象，不需要同名

        也就是说：

        1. 用 `gcloud pubsub topics create billing-alerts` 创建的是消息主题

        2. 在 Billing -> Budgets & alerts 页面里创建预算时，填写的名称才是 `EXPECTED_BUDGET_NAME`

        3. 然后再把这个预算 `EXPECTED_BUDGET_NAME`连接到 `billing-alerts` 这个 topic

## 第 5 步：创建预算提醒

以下在GCP控制台界面中操作：

操作路径：左上角三条横线 (或直接在顶部搜索框中搜索 `billing`) --> `Billing` --> `Budgets & alerts` --> `Create budget`

1. `Name` 输入框填入 budget name，**注意**，这里的名字将会在**第7步**实际部署时用到，部署时务必与这里填写的名字保持完全一致 (大小写，连字符), 例如: `Hard-Stop-Budget`;

2. `Time range` 视自己需要选择即可，一般选择 `Monthly`;

3. `Projects` 选择你需要保护的 Project;

4. `Services` 默认全选，不用改动;

5. `Savings` **注意**：如果你有 credit 的话，建议不要勾选 `Other Savings` 中的 `Free tier credits` 和 `Promotional credits`。这里的逻辑是这样的：勾选的话，设置的金额将会是用量金额减去 credits，如果你只是想监控每月用量不要超过 credits 额度以免用真金白银支付实际费用，那么你勾选之后，在减掉你账户中的 credits 之后达到你的设定值才会触发停机操作。

    举例说明：

    假设你设定的报警/停机阈值为 $100/Month, 你的账户中有 $300 的 credits，当月你的用量产生了 $101：

    - 勾选 `Free tier credits` 和 `Promotional credits`：

        $300 credits 全部用光，然后又产生了 $100 用量，此时触发报警并停机，你要为此支付 $100 的真金白银；

    - 不勾选`Free tier credits` 和 `Promotional credits`：

        达到了 $100 的报警阈值，此时触发报警并停机，这 $100 是在你的 credits 额度内，只扣减的你的 credits，你不用花费 $100 的真金白银。

6. `Amount` 设定的阈值，根据你的实际需要填写。建议**小于你可负担的最大损失**;

7. `Actions` 勾选 `Connect a Pub/Sub topic to this budget`，在下拉菜单中选择**第2步**中创建的 Pub/Sub topic: `billing-alerts`;

8. 最后点击 `Finish` 即可.

## 第 6 步：给当前使用的默认服务账号授权

授权之前，到 GCP 控制台主页获取 `Project number`:

![Project number](/snapshots/project_number.png)

**注意**：请将下面的`XXXXXXXXXXX`替换为你的`project number`，`YOUR_PROJECT_ID` 替换为你自己项目的 `Project ID`。

### 第一步：先给当前使用的默认服务账号授权`cloudbuild.builds.builder`权限

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
 --member=serviceAccount:XXXXXXXXXXX-compute@developer.gserviceaccount.com \
 --role=roles/cloudbuild.builds.builder 
 ```

### 第二步：赋予 Pub/Sub 服务账号“创建令牌”的权限

Pub/Sub 需要生成一个身份令牌（Token）来证明自己。运行以下命令 (**请将 `YOUR_PROJECT_ID` 替换为你自己项目的 `Project ID`**)：

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:service-XXXXXXXXXXX@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountTokenCreator"
```

### 第三步：赋予云函数触发器“调用 Cloud Run”的权限

默认的触发器使用的是计算引擎服务账号，需要让它有资格调用你的 billing-killer。运行以下命令：

```bash
gcloud run services add-iam-policy-binding billing-killer \
    --region=us-central1 \
    --member="serviceAccount:XXXXXXXXXXX-compute@developer.gserviceaccount.com" \
    --role="roles/run.invoker"
```

### 第四步：在GCP控制台授予 `Billing Account Administrator` 权限给你的服务账号 `XXXXXXXXXXX-compute@developer.gserviceaccount.com`

操作路径：左上角三条横线  (或直接在顶部搜索框中搜索 `billing`)  --> `Billing` --> `Account Management` --> 右侧边栏 `Add principal` --> `New pricipals` 输入框中输入你的服务账号 `XXXXXXXXXXX-compute@developer.gserviceaccount.com` --> `Select a role` 选择 `Billing Account Administrator` --> `Save`

![billing_management](/snapshots/billing_management.png)

## 第 7 步：部署到Cloud Run functions

**注意**: 请将下面的 `YOUR_PROJECT_ID` 替换为你自己项目的 `Project ID`：

![project_id](/snapshots/project_number.png)

第一次部署时，先不要真实停用 billing，建议先用 `SIMULATE_DEACTIVATION=true` 部署，验证消息链路、权限、日志都正常，再切到真实模式。

部署“模拟验证”命令：

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

说明：

1. `TARGET_PROJECT_ID`
    
    换成你要保护的真实项目 ID。

2. `EXPECTED_BUDGET_NAME`
    
    换成你在**第5步** Billing Budget 页面设置的预算名称，保证完全一致，**不是 Pub/Sub topic 名**。

3. `SIMULATE_DEACTIVATION=true`
    
    可以验证通知链路和代码逻辑。先做演练，确认逻辑正确。

4. 可能会提示API `[eventarc.googleapis.com] not enabled on project [YOUR_PROJECT_ID]`，输入`y`确认即可。

5. 建议显式开启 `--retry`
    
    当前 `main.py` 在关键失败时会抛错，开启重试后，平台才有机会对临时性失败再次投递事件。

建议：

1. 一个预算只保护一个项目

2. 一个预算只连一个专用 topic


## 第 8 步：模拟验证模式

先验证“通知能到函数、函数能识别、日志能写出”，不要一上来就真实断电。

推荐验证顺序：

1. 保持 `SIMULATE_DEACTIVATION=true`

2. 进入 `Pub/Sub` 模拟达到用量阈值，发送测试消息：

    操作路径：左上角三条横线  (或直接在顶部搜索框中搜索 `Pub/Sub`)  --> `Pub/Sub` --> `Topics` --> 点击 `Topic ID` (本例中为 `billing-alerts` ) --> `Messages` --> 点击 Step 1 中的 `Publish Message`

    ![pub/sub](/snapshots/pub_sub.png)

    在 `Message Body` 中 copy-paste 下面这段代码，点击 `Publish`。

    **注意**：请将下面的 `YOUR_BUDGET_AMOUNT` 替换为你在**第5步**中创建的 `Budget alerts` 中的提醒阈值，例如 `100`，将 `YOUR_COST_AMOUNT` 替换为稍大于提醒阈值的值，此例中为 `100.5`:

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

3. 到 `Cloud Run` 中的日志里检查是否出现类似以下日志：

    操作路径：左上角三条横线  (或直接在顶部搜索框中搜索 `Cloud Run`) --> `Cloud Run` --> 点击 `billing-killer` --> `Logs`

   - 收到预算通知
   - 识别到预算已超限
   - 进入 shutdown flow
   - 因为 simulation mode，只记录“模拟停用”

    如下面截图所示：

    ![cloud_run_logs](/snapshots/cloud_run_logs.png)

    如果这些日志都正常，说明：

    1. Budget -> Pub/Sub -> Function 链路正常

    2. 代码能够正确解析通知

    3. 环境变量 `TARGET_PROJECT_ID`, `EXPECTED_BUDGET_NAME` 没配错

## 第 9 步：切换到真实停用模式

验证通过后，把环境变量改成真实模式，直接运行下面的命令即可，无须删除之前部署的模拟验证版本，将会自动覆盖：

 **请将下面的 `YOUR_PROJECT_ID` 替换为你自己项目的 `Project ID`**

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

到这一步后，一旦预算通知到达且 `costAmount >= budgetAmount`，函数会尝试解除目标项目的 billing 绑定。

## 第 10 步：建议的上线后检查项

上线后建议额外确认以下内容：

1. 该函数是否真的部署在你预期的项目中

2. `TARGET_PROJECT_ID` 是否就是要保护的项目

3. `EXPECTED_BUDGET_NAME` 是否和预算页面完全一致

4. 函数日志里没有持续出现权限错误

6. 使用一个全新的小项目做一次真实验证，`budget_amount` 填写 $1，至少做一次真实解绑演练，或者明确接受未实弹验证的风险

## 真实停用触发后的预期现象

如果成功，通常会出现这些结果：

1. 目标项目与 billing account 解绑

2. 项目内付费资源开始停机

3. 同项目里的这个函数本身也会受影响

4. 项目恢复需要你手工重新绑定 billing，并按需重启服务

## 失败时最常见的原因

如果将来没有按预期停用，优先排查这几项：

1. `SIMULATE_DEACTIVATION` 还保持在 `true`

2. service account 没有足够权限

3. 项目被 lock 到 billing account

4. `EXPECTED_BUDGET_NAME` 与实际预算名不一致

5. 预算通知尚未到达

6. 预算或 Pub/Sub 配置连错项目 / 连错 topic

7. 函数没有开启重试 ( `--retry` )，导致一次临时失败后事件未再次处理

## 建议的最终配置

如果你现在是单项目、单预算、单 billing account 的简单场景，建议最终采用下面这组策略：

1. 一个项目一个预算

2. 一个预算一个专用 Pub/Sub topic

3. 一个函数只保护一个项目

4. 上线前先用 `SIMULATE_DEACTIVATION=true` 演练

5. 演练通过后再改成 `false`

## 最后提醒

这套方案是极其有效的**“终极保险丝”**和**“事后自动止损机制”**，但**永远不要把它当成你安全防护的唯一防线**。  

因为 GCP 的账单计算和预算通知天然存在一定的时间延迟，从超支发生到拔掉网线，可能会有数分钟到数小时的窗口期。

为了真正把风险压到最低，你应该将本项目与以下**“前置防线”**结合使用：

1. **设置大模型 API 的配额（Quotas）上限（应对 AI Agent 暴走的最优解）**：
   在 GCP 的 `Quotas` 页面，强烈建议为 Gemini 等大模型 API 设置 **每分钟请求数 (RPM)** 和 **每天 Token 数 (TPD)** 的硬性配额上限。这样就算 OpenClaw 等 Agent 失控陷入死循环，也会被 API 网关层直接拦截，无法在短时间内刷出天价账单。

2. **为 API Key 设置来源限制**：
   限制 Key 只能从特定的 IP 地址、特定的域名，或者特定的 iOS/Android 应用包名中发起调用。

3. **为 API Key 设置调用范围限制**：
   限制这个 Key 只能调用某几个特定的 API（比如只允许调用 Gemini API，坚决不允许它调用 Compute Engine 等高收费接口）。

4. **践行最小权限原则 (PoLP)**：
   服务账号（Service Account）只给赋予完成当前任务所需的最少权限，不要为了省事给 `Owner` 或 `Editor`。

5. **隔离开发与生产环境**：
   把测试、实验性 AI Agent、生产环境拆分到不同的 GCP 项目中。为高风险的实验项目设置极低的预算，并绑定本项目的“拔网线”程序。

最后，给你的终极建议是：**设定的预算金额，应当低于你真正能承受的最大损失，为账单延迟留出充足的缓冲空间。**

## 附录：如何查看 / 设置 / 修改环境变量

下面这些命令都以函数名 `billing-killer`、区域 `us-central1` 为例 (前面的部署命令中已经使用了这些参数，如果你是 copy paste，则可以安全忽略)。  
如果你的函数名或区域不同，请替换对应值。

### 查看当前环境变量

```bash
gcloud functions describe billing-killer \
    --gen2 \
    --region us-central1
```

在返回结果里查看 `serviceConfig.environmentVariables`。

### 第一次部署时设置环境变量

如果函数还没部署，直接在 `gcloud functions deploy` 时一起带上 (**请将下面的 `YOUR_PROJECT_ID` 替换为你自己项目的 `Project ID`**)：

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

说明：

1. `--set-env-vars` 会在这次部署时写入整组环境变量。
2. 如果你后面再次用 `deploy` 并继续传 `--set-env-vars`，建议把你需要保留的变量一次性都带上，避免自己记混。

### 修改某个环境变量

如果函数已经存在，想只改其中一个或几个值，推荐用：

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --region us-central1 \
    --update-env-vars SIMULATE_DEACTIVATION=false
```

例如，把预算名称改掉：

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --region us-central1 \
    --update-env-vars EXPECTED_BUDGET_NAME=My-New-Budget
```

例如，同时改多个变量 (**请将下面的 `YOUR_PROJECT_ID` 替换为你自己项目的 `Project ID`**)：

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --region us-central1 \
    --update-env-vars TARGET_PROJECT_ID=YOUR_PROJECT_ID,SIMULATE_DEACTIVATION=false,EXPECTED_BUDGET_NAME=Hard-Stop-Budget
```

### 删除某个环境变量

如果你想取消预算名校验，可以删除 `EXPECTED_BUDGET_NAME`：

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --region us-central1 \
    --remove-env-vars EXPECTED_BUDGET_NAME
```

### 清空并重设整组环境变量

如果你担心历史环境变量残留，最稳妥的方法是先清空，再重新设置：

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --region us-central1 \
    --clear-env-vars
```

然后重新部署并带上完整变量集合 (**请将下面的 `YOUR_PROJECT_ID` 替换为你自己项目的 `Project ID`**)：

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

### 推荐的两个常用切换命令

切到模拟模式：

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --region us-central1 \
    --update-env-vars SIMULATE_DEACTIVATION=true
```

切到真实停用模式：

```bash
gcloud functions deploy billing-killer \
    --gen2 \
    --region us-central1 \
    --update-env-vars SIMULATE_DEACTIVATION=false
```
### 推荐做法

1. 第一次部署时，用 `--set-env-vars` 一次性写全。
2. 日常改单个值时，用 `--update-env-vars`。
3. 取消某个可选变量时，用 `--remove-env-vars`。
4. 如果你怀疑环境变量已经混乱，用 `--clear-env-vars` 后再完整重设。
