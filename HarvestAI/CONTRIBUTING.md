# Contributing to HarvestAI

Thank you for your interest in contributing to HarvestAI! This guide will help you understand our development workflow, testing requirements, and submission process.

## Getting Started

### 1. Fork and Clone
```bash
git clone https://github.com/YOUR_USERNAME/HarvestAI.git
cd HarvestAI
```

### 2. Set Up Development Environment

**Backend (Python):**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

**Frontend (React):**
```bash
cd frontend
npm install
npm run dev
```

### 3. Install Pre-Commit Hooks
```bash
pip install pre-commit
pre-commit install
```

This ensures:
- No secrets are accidentally committed
- Code is properly formatted
- Security checks pass locally

## Development Workflow

### 1. Create a Feature Branch
```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

Use meaningful branch names:
- `feature/add-soil-moisture-alert`
- `fix/weather-api-timeout`
- `docs/update-architecture`

### 2. Make Your Changes
- Keep commits atomic (one logical change per commit)
- Write clear commit messages
- Include tests for new features
- Update documentation as needed

### 3. Test Locally

**Python (Backend):**
```bash
# Run tests
pytest backend/lambda_functions/

# Lint code
pylint backend/lambda_functions/

# Check for security issues
bandit -r backend/
```

**JavaScript (Frontend):**
```bash
cd frontend
npm run dev      # Test locally
npm run build    # Verify build succeeds
npm run lint     # Check for linting issues
```

### 4. Push and Create a Pull Request
```bash
git push origin feature/your-feature-name
```

Then create a PR on GitHub. Use the PR template to:
- Describe your changes
- Link related issues
- Highlight any security considerations
- Confirm testing completed

## Code Standards

### Python
- Follow PEP 8
- Use type hints where possible
- Add docstrings to functions
- Minimize external dependencies

```python
def calculate_gdd(temp_max: float, temp_min: float, base_temp: float = 50.0) -> float:
    """Calculate Growing Degree Days.
    
    Args:
        temp_max: Maximum temperature (°F)
        temp_min: Minimum temperature (°F)
        base_temp: Base temperature for calculation (default 50°F)
    
    Returns:
        Growing Degree Days as float
    """
    avg_temp = (temp_max + temp_min) / 2
    return max(0, avg_temp - base_temp)
```

### JavaScript/React
- Use ES6+ syntax
- Add JSDoc comments for components
- Keep components focused (single responsibility)
- Use meaningful variable names

```javascript
/**
 * FieldDashboard - Main dashboard component for field monitoring
 * @param {string} fieldId - ID of the field to display
 * @returns {React.ReactElement}
 */
export default function FieldDashboard({ fieldId }) {
  // Component logic
}
```

### Infrastructure (YAML)
- Use clear resource names
- Add descriptions for non-obvious configurations
- Keep related resources together
- Use consistent indentation (2 spaces)

## Security Considerations

### Secrets Management
- **NEVER** hardcode AWS keys, API tokens, or passwords
- Use AWS Secrets Manager for production secrets
- Use `.env.local` for local development (excluded from git)
- All commits are scanned for exposed secrets

### Code Review
- Security-sensitive code requires extra scrutiny
- Pay attention to AWS IAM permissions (least privilege)
- Validate all external API inputs
- Sanitize database queries (though using ORM/DynamoDB helps)

### Testing
- Test error cases and edge conditions
- Test with realistic data volumes
- Verify Lambda timeout and memory settings
- Check CloudWatch logs for errors

## Commit Message Guidelines

Write clear, concise commit messages:

```
<type>: <subject>

<body (optional)>

<footer (optional)>
```

**Types:**
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation update
- `style` - Code style change (no logic change)
- `refactor` - Code refactor
- `perf` - Performance improvement
- `test` - Test additions
- `ci` - CI/CD configuration

**Examples:**
```
feat: Add soil moisture anomaly detection to daily batch

This implements soil moisture trend analysis in the daily batch function,
using a 30-day rolling average to detect anomalies.

Closes #42
```

```
fix: Handle missing weather data gracefully

Previously the daily batch would fail if weather data was unavailable
for a field. Now it logs the error and continues processing.

Fixes #87
```

## Documentation

### When to Update Docs
- Adding a new Lambda function → add to docs/DEPLOYMENT.md
- Changing API contracts → update docs/API_CONTRACTS.md
- Modifying database schema → update related docs
- Adding external API integrations → document in README

### Documentation Format
- Use Markdown for readability
- Include code examples for complex features
- Add architecture diagrams when helpful
- Document assumptions and limitations

## Testing

### Unit Tests (Optional but Encouraged)
For new features, consider adding tests:

**Backend (Python):**
```bash
pytest backend/lambda_functions/ -v
```

**Frontend (JavaScript):**
```bash
cd frontend && npm test -- --run
```

### Integration Testing
- Test with real AWS services in dev environment
- Verify end-to-end flows in staging
- Check CloudWatch logs for errors/warnings

### Manual Testing
- Test in dev environment before submitting PR
- Verify frontend UI changes in multiple browsers
- Test error scenarios and edge cases

## Performance Considerations

### Lambda Functions
- Lambda timeout: Consider Batch=900s, Onboarding=60s, GetStatus=30s
- Memory allocation: 256MB for lightweight, 1024MB for compute-intensive
- Cold start impact: Monitor for slow responses
- External API calls: Add timeouts and retry logic

### Frontend
- Bundle size: Monitor with `npm run build`
- API polling: Currently 60s interval for status updates
- Data fetching: Batch requests where possible

### Database
- DynamoDB: Monitor throttling and hot partitions
- Query patterns: Use efficient key structures
- TTL: Consider 90-day retention for time-series data

## Need Help?

### Questions?
- Check existing issues and PRs
- Review documentation in `/docs`
- Open a GitHub discussion

### Issues?
- Report bugs using the bug report template
- Include logs and error messages
- Provide steps to reproduce

### Security Concerns?
- DO NOT create a public issue
- Email maintainers privately
- Include steps to reproduce if possible

## Code Review Process

1. **Submission**: Create a PR with detailed description
2. **Automated Checks**: Security, linting, build tests run automatically
3. **Review**: Maintainers review for:
   - Code quality and style
   - Security implications
   - Test coverage
   - Documentation updates
4. **Feedback**: Address reviewer comments or discuss alternatives
5. **Approval**: Requires at least 1 approval
6. **Merge**: Squash and merge to `main` (or rebase if preferred)

## Recognition

Contributors are recognized in:
- GitHub commit history
- README.md contributors section (if applicable)
- Release notes for significant contributions

## License

By contributing to HarvestAI, you agree that your contributions will be licensed under the same license as the project.

---

Thank you for making HarvestAI better! 🌾
