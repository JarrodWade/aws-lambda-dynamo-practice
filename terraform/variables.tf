variable "project_name" {
  description = "Short name used to prefix all created resources."
  type        = string
  default     = "billing-bot-practice"
}

variable "region" {
  description = "AWS region for all resources. Bedrock model availability varies by region."
  type        = string
  default     = "us-east-1"
}

variable "bedrock_model_id" {
  description = "Bedrock model ID used by the Lambda. Default is Amazon Nova Micro (cheap)."
  type        = string
  default     = "amazon.nova-micro-v1:0"
}

variable "max_output_tokens" {
  description = "Hard cap on tokens generated per response."
  type        = number
  default     = 300
}

variable "session_ttl_seconds" {
  description = "TTL for session/message items in DynamoDB."
  type        = number
  default     = 604800 # 7 days
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the Lambda function."
  type        = number
  default     = 7
}

variable "monthly_budget_usd" {
  description = "AWS Budgets monthly cost cap for the project (USD)."
  type        = number
  default     = 10
}

variable "budget_alert_email" {
  description = "Email address that receives AWS Budgets alerts."
  type        = string
}
