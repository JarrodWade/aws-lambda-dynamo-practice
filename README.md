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

| itemType            | PK              | SK                         | Notes                             |
| ------------------- | --------------- | -------------------------- | --------------------------------- |
| `ConversationSession` | `USER#<id>`   | `SESSION#<id>`             | TTL via `expiresAt`               |
| `ChatMessage`       | `USER#<id>`    | `MSG#<isoTs>#<msgId>`       | One per user/bot message          |
| `Idempotency`       | `IDEMPOTENCY#<reqId>` | `REQUEST`            | Prevents duplicate processing      |

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
