output "api_endpoint" {
  description = "Base URL for the HTTP API. POST to /chat."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "chat_url" {
  description = "Full URL for the chat endpoint."
  value       = "${aws_apigatewayv2_api.http.api_endpoint}/chat"
}

output "table_name" {
  description = "DynamoDB table name."
  value       = aws_dynamodb_table.chat.name
}

output "lambda_function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.chat.function_name
}

output "log_group" {
  description = "CloudWatch log group for the Lambda."
  value       = aws_cloudwatch_log_group.lambda.name
}
