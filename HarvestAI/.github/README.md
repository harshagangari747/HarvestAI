# GitHub Configuration

This folder contains GitHub-specific configuration files for the HarvestAI project.

## Contents

### Workflows (`/workflows`)
- **security.yml** - Runs security checks on every push and PR
  - Secret detection (truffleHog)
  - CloudFormation linting
  - Python/Node dependency vulnerability scanning
  - YAML validation

### Issue Templates (`/ISSUE_TEMPLATE`)
- **architecture-debt.md** - Track architectural improvements
- **bug-report.md** - Report bugs with structured information

### Pull Request Template
- **PULL_REQUEST_TEMPLATE.md** - Standardizes PR descriptions and checklists

## Security Workflows

The security workflow runs automatically on:
- Push to `main` or `develop`
- All pull requests

It checks for:
1. **Secrets** - Uses truffleHog to detect API keys, tokens, credentials
2. **Infrastructure** - Validates CloudFormation YAML templates
3. **Code Quality** - Python linting (pylint)
4. **Dependencies** - Checks for known vulnerabilities in Python & Node packages

## Branch Protection Rules

For the `main` branch:
- Requires pull request review (minimum 1 approval)
- Requires status checks to pass (security.yml workflow)
- Requires branches to be up to date
- Dismiss stale reviews when new commits are pushed

## Pre-Commit Hooks

To set up local security checks before committing:

```bash
pip install pre-commit
pre-commit install
```

This will:
- Detect secrets locally before they're committed
- Check for private keys, large files
- Lint YAML and Python files
- Format code (Prettier for JS/JSON)
- Run Python security checks (bandit)

## Recommended GitHub Settings

1. **Settings → Branches → Branch protection rules**
   - Enable for `main` branch
   - Require pull request reviews
   - Require status checks to pass

2. **Settings → Code security and analysis**
   - Enable "Secret scanning"
   - Enable "Dependabot alerts"
   - Enable "Dependabot security updates"

3. **Settings → Actions**
   - Review workflow permissions
   - Set default to "read"

4. **Settings → Audit log**
   - Regularly review for suspicious activity

## Creating Issues from Templates

When creating a new issue:
1. Click "New Issue"
2. Select the appropriate template
3. Fill in all required fields
4. Add relevant labels and assignees

## Workflow Secrets

If deploying via GitHub Actions, store sensitive values in:
**Settings → Secrets and variables → Actions**

Examples:
- AWS credentials (for deployment)
- API tokens
- Database passwords

These are encrypted and masked in logs.
