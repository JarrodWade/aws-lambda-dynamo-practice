# aws-lambda-dynamo-practice

A tiny **billing chatbot** sandbox to practice the AWS pieces:

- **API Gateway (HTTP API)** &rarr; **Lambda (Python 3.12)** &rarr; **DynamoDB** + **Bedrock** (Amazon Nova Micro)
- **AWS Budgets** alerts at 50% / 80% / 100% of `$10/month`
- **CloudWatch Logs** retention `7 days`
- **DynamoDB TTL** for session/message cleanup
- All infra managed with **Terraform**

> Designed to fit in roughly `$10/month` for solo practice usage.

## Architecture

```
client (curl/Postman)
        |
        v
API Gateway (HTTP API, POST /chat)
        |
        v
Lambda (Python)
   |          \
   |           \-- Bedrock (amazon.nova-micro-v1:0)
   v
DynamoDB (single table: PK / SK, TTL on `expiresAt`)
```

### DynamoDB item shapes

| itemType              | PK                    | SK                       | Notes                                |
| --------------------- | --------------------- | ------------------------ | ------------------------------------ |
| `ConversationSession` | `USER#<id>`           | `SESSION#<id>`           | TTL via `expiresAt`                  |
| `ChatMessage`         | `USER#<id>`           | `MSG#<isoTs>#<msgId>`    | One per user/bot message; TTL        |
| `PaymentIntent`       | `USER#<id>`           | `PAYMENT#<paymentId>`    | State machine; appears on GSI1       |
| `Idempotency`         | `IDEMPOTENCY#<reqId>` | `REQUEST`                | Prevents duplicate processing; TTL   |

### GSI1 — payment queue by status

```
GSI1PK = PAYMENT_STATUS#<status>     // e.g. PAYMENT_STATUS#PENDING
GSI1SK = <createdAt>#<paymentId>     // time-ordered within a status
```

Lets you query things like "all PENDING payments across all users" without scanning.

## API routes

All routes go to a single Lambda router (`lambda/handler.py`).

| Method | Path                          | Body / Query                                              | Description                                 |
| ------ | ----------------------------- | --------------------------------------------------------- | ------------------------------------------- |
| POST   | `/chat`                       | `{userId, sessionId?, message}`                           | Chat turn through Bedrock (Nova Micro)      |
| GET    | `/history`                    | `?userId=&limit=20&cursor=<prevSK>`                       | Paginated message history (newest first)    |
| POST   | `/payments`                   | `{userId, amount, currency?, paymentId?}`                 | Create PENDING `PaymentIntent`              |
| GET    | `/payments`                   | `?userId=` **or** `?status=PENDING\|PAID\|...`            | List by user (base table) or status (GSI1)  |
| POST   | `/payments/{paymentId}/pay`   | `{userId, confirmationId}`                                | Conditional `PENDING -> PAID` transition    |

### Try it

```bash
BASE=$(terraform -chdir=terraform output -raw api_endpoint)

# create
curl -sS -X POST "$BASE/payments" -H 'content-type: application/json' \
  -d '{"userId":"demo-user","amount":142.67}' | jq

# list pending across all users (GSI1)
curl -sS "$BASE/payments?status=PENDING" | jq

# pay it (replace pay-XXXX)
curl -sS -X POST "$BASE/payments/pay-XXXX/pay" -H 'content-type: application/json' \
  -d '{"userId":"demo-user","confirmationId":"conf-001"}' | jq

# message history
curl -sS "$BASE/history?userId=demo-user&limit=10" | jq
```

## One-time setup

### 1. Create / log in to your AWS account

If you don't have one yet, sign up at <https://aws.amazon.com/>. You'll need a card on file but the Free Tier covers most of this stack.

### 2. Create an IAM user with programmatic access

In the AWS Console:

1. Go to **IAM &rarr; Users &rarr; Create user**.
2. Name it e.g. `practice-cli`.
3. Attach policy **`AdministratorAccess`** (fine for a personal sandbox; tighten later).
4. After creation, open the user &rarr; **Security credentials &rarr; Create access key &rarr; CLI**.
5. Save the **Access key ID** and **Secret access key**.

### 3. Configure the AWS CLI

```bash
aws configure
# AWS Access Key ID:     <paste>
# AWS Secret Access Key: <paste>
# Default region name:   us-east-1
# Default output format: json

aws sts get-caller-identity   # should print your account/user
```

### 4. Enable Bedrock model access

Bedrock models are off by default. In the AWS Console:

1. Go to **Amazon Bedrock** (in `us-east-1`).
2. Open **Model access** in the left nav.
3. Click **Modify model access**, enable **Amazon Nova Micro** (and any others you want), submit.
4. Wait for status &rarr; **Access granted** (usually seconds).

## Deploy

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# edit terraform.tfvars and set budget_alert_email to your real email

make init
make plan
make apply
```

Confirm the budget alert email in the message AWS sends so notifications work.

## Try it

```bash
make test-api MSG="Hi, what can you help me with?"
make test-api MSG="I want to pay my bill"
```

Tail logs in another terminal:

```bash
make logs
```

## Web UI (no build, just open it)

A tiny single-file UI lives at `web/index.html` &mdash; chat panel + payments panel.

```bash
make ui                          # serves it on http://localhost:8000
```

> Don't open the file directly with `file://` &mdash; browsers send `Origin: null`
> on those requests and API Gateway won't return CORS headers, so calls fail
> with "Failed to fetch". `make ui` just runs `python3 -m http.server` so the
> page loads from a real `http://localhost` origin.

Then in the top bar:

1. Paste your **API URL** (run `terraform -chdir=terraform output -raw api_endpoint`).
2. Set a **User** id (e.g. `demo-user`).
3. Both values are saved to `localStorage` so you only do it once per browser.

The UI uses CORS (`*`) on the HTTP API. Fine for solo practice; lock it down to a real origin before sharing.

## Inspect data in DynamoDB

```bash
aws dynamodb scan \
  --table-name billing-bot-practice-chat \
  --max-items 20
```

## Tear it down

```bash
make destroy
```

## Cost guardrails baked in

- DynamoDB on-demand (pay per request)
- Lambda 256MB / 20s timeout
- Bedrock Nova Micro + `MAX_OUTPUT_TOKENS=300`
- CloudWatch log retention `7 days`
- AWS Budget at `$10/month` with alerts at 50% / 80% / 100%

If costs ever look weird, run `make destroy` &mdash; everything in this repo can be rebuilt fresh.
