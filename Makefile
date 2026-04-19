.PHONY: init plan apply destroy fmt validate test-local test-api logs tail

TF := terraform -chdir=terraform

init:
	$(TF) init

fmt:
	$(TF) fmt -recursive

validate:
	$(TF) validate

plan:
	$(TF) plan

apply:
	$(TF) apply

destroy:
	$(TF) destroy

# Hit the deployed endpoint. Usage: make test-api MSG="hello"
MSG ?= Hello, can you help me pay my bill?
USER_ID ?= demo-user
test-api:
	@URL=$$($(TF) output -raw chat_url); \
	echo "POST $$URL"; \
	curl -sS -X POST "$$URL" \
		-H 'content-type: application/json' \
		-d "{\"userId\":\"$(USER_ID)\",\"message\":\"$(MSG)\"}" | jq .

# Tail the Lambda log group
logs:
	@LG=$$($(TF) output -raw log_group); \
	aws logs tail "$$LG" --since 10m --follow

# Serve the static UI on http://localhost:8000 (browsers block CORS from file://)
UI_PORT ?= 8000
ui:
	@echo "Open http://localhost:$(UI_PORT)/"; \
	cd web && python3 -m http.server $(UI_PORT)
