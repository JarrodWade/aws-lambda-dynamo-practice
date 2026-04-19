data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/build/lambda.zip"
  excludes = [
    "__pycache__",
    "requirements.txt",
  ]
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}-chat"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "chat" {
  function_name    = "${var.project_name}-chat"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 20
  memory_size      = 256

  environment {
    variables = {
      TABLE_NAME          = aws_dynamodb_table.chat.name
      BEDROCK_MODEL_ID    = var.bedrock_model_id
      BEDROCK_REGION      = var.region
      MAX_OUTPUT_TOKENS   = tostring(var.max_output_tokens)
      SESSION_TTL_SECONDS = tostring(var.session_ttl_seconds)
      MAX_HISTORY_TURNS   = "10"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_inline,
  ]
}
