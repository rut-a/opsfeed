.PHONY: test check fmt

test:
	python -m pytest

fmt:
	terraform fmt -recursive

check:
	terraform fmt -check -recursive
	terraform init -backend=false
	terraform validate
