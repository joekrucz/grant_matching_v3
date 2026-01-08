# Testing Guide

This document explains how to run tests for the Grants Aggregator V2 application.

## Setup

1. **Install test dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Verify pytest is installed:**
   ```bash
   pytest --version
   ```

## Running Tests

### Run All Tests
```bash
pytest
```

### Run Tests for Specific App
```bash
# Test companies app
pytest companies/tests/

# Test grants app
pytest grants/tests/

# Test users app
pytest users/tests/
```

### Run Specific Test File
```bash
pytest companies/tests/test_models.py
```

### Run Specific Test
```bash
pytest companies/tests/test_models.py::TestCompany::test_company_str_with_number
```

### Run with Coverage Report
```bash
pytest --cov=. --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`.

### Run in Verbose Mode
```bash
pytest -v
```

### Run Tests in Parallel (faster)
```bash
pytest -n auto
```

(Requires `pytest-xdist`: `pip install pytest-xdist`)

## Test Structure

```
grants_aggregator_V2/
├── companies/
│   └── tests/
│       ├── test_models.py      # Company model tests
│       ├── test_views.py       # View authorization tests
│       ├── test_services.py   # Service tests (with mocking)
│       ├── test_security.py   # Security/SSRF tests
│       └── factories.py       # Test data factories
├── grants/
│   └── tests/
│       ├── test_models.py      # Grant model tests
│       ├── test_api_views.py  # API endpoint tests
│       └── factories.py
├── users/
│   └── tests/
│       ├── test_models.py      # User model tests
│       ├── test_views.py       # Authentication tests
│       └── factories.py
└── grants_aggregator/
    └── tests/
        ├── test_security_utils.py  # Security utility tests
        └── test_health.py          # Health check tests
```

## Test Categories

### Model Tests
Test model methods, properties, and business logic:
- `test_models.py` - Tests for model methods like `get_computed_status()`, `sic_codes_array()`, etc.

### View Tests
Test view authorization, form handling, and redirects:
- `test_views.py` - Tests that users can only access their own data, admins can access everything, etc.

### Service Tests
Test external service integrations (with mocking):
- `test_services.py` - Tests for CompaniesHouseService, ChatGPTMatchingService using mocked HTTP requests

### Security Tests
Test security functions:
- `test_security.py` - SSRF protection, URL validation, private IP detection

### API Tests
Test API endpoints:
- `test_api_views.py` - Tests for scraper service API endpoints

## Writing New Tests

### Example: Model Test
```python
@pytest.mark.django_db
class TestMyModel:
    def test_my_method(self):
        obj = MyModelFactory()
        result = obj.my_method()
        assert result == expected_value
```

### Example: View Test
```python
@pytest.mark.django_db
class TestMyView:
    def test_view_requires_login(self, client):
        response = client.get(reverse('myapp:my_view'))
        assert response.status_code == 302  # Redirect to login
    
    def test_view_accessible_when_logged_in(self, client, user):
        client.force_login(user)
        response = client.get(reverse('myapp:my_view'))
        assert response.status_code == 200
```

### Example: Service Test with Mocking
```python
@responses.activate
def test_external_api_call():
    responses.add(
        responses.GET,
        'https://api.example.com/endpoint',
        json={'data': 'value'},
        status=200
    )
    
    result = MyService.call_api()
    assert result['data'] == 'value'
```

## Test Configuration

- **Settings**: `grants_aggregator/test_settings.py` - Uses in-memory SQLite for fast tests
- **Config**: `pytest.ini` - Pytest configuration
- **Fixtures**: `conftest.py` - Shared test fixtures

## Continuous Integration

Tests can be run in CI/CD pipelines. Example GitHub Actions:

```yaml
- name: Run tests
  run: pytest --cov=. --cov-report=xml
```

## Troubleshooting

### Tests fail with "Database locked"
- This usually happens with SQLite. The test settings use in-memory SQLite which should avoid this.
- Try running tests sequentially: `pytest` (without `-n auto`)

### Import errors
- Make sure you're in the project root directory
- Verify all dependencies are installed: `pip install -r requirements.txt`

### Coverage not showing
- Make sure `pytest-cov` is installed: `pip install pytest-cov`
- Run with `--cov` flag: `pytest --cov=.`

## Best Practices

1. **Use factories** - Don't create test data manually, use factories
2. **Test edge cases** - Test both success and failure paths
3. **Mock external services** - Don't make real API calls in tests
4. **Keep tests fast** - Use in-memory database, avoid slow operations
5. **Test authorization** - Always test that users can only access their own data
6. **Test security** - Test SSRF protection, input validation, etc.

## Coverage Goals

- **Minimum**: 70% coverage
- **Target**: 80%+ coverage
- **Focus areas**: Models, views, services, security functions

Run coverage report to see current coverage:
```bash
pytest --cov=. --cov-report=term-missing
```






