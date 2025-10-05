# Publishing to PyPI

This guide explains how to publish the `idempotent-middleware` package to PyPI.

## Prerequisites

1. **PyPI Account**: Create accounts on both:
   - Test PyPI: https://test.pypi.org/account/register/
   - Production PyPI: https://pypi.org/account/register/

2. **API Tokens**: Generate API tokens for automated uploads:
   - Test PyPI: https://test.pypi.org/manage/account/token/
   - Production PyPI: https://pypi.org/manage/account/token/

   Save these tokens securely - you'll need them for uploading.

3. **Install Build Tools** (already done):
   ```bash
   pip install build twine
   ```

## Building the Package

### 1. Update Version

Edit `pyproject.toml` and bump the version:
```toml
[project]
version = "0.1.0"  # Change to "0.1.1", "0.2.0", etc.
```

### 2. Clean Previous Builds

```bash
rm -rf dist/ build/ src/*.egg-info
```

### 3. Build Distribution Files

```bash
python -m build
```

This creates:
- `dist/idempotent_middleware-X.Y.Z.tar.gz` (source distribution)
- `dist/idempotent_middleware-X.Y.Z-py3-none-any.whl` (wheel distribution)

### 4. Validate the Build

```bash
twine check dist/*
```

All checks should pass.

## Testing on Test PyPI

Always test on Test PyPI before publishing to production PyPI:

### 1. Upload to Test PyPI

```bash
twine upload --repository testpypi dist/*
```

When prompted, enter:
- Username: `__token__`
- Password: Your Test PyPI API token (starts with `pypi-`)

### 2. Test Installation from Test PyPI

Create a fresh virtual environment and test:

```bash
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ idempotent-middleware
```

Note: `--extra-index-url` is needed because Test PyPI doesn't have all dependencies.

### 3. Verify Installation

```python
python -c "from idempotent_middleware import IdempotencyConfig; print('✓ Import successful')"
```

## Publishing to Production PyPI

Once testing is complete:

### 1. Upload to PyPI

```bash
twine upload dist/*
```

When prompted, enter:
- Username: `__token__`
- Password: Your PyPI API token (starts with `pypi-`)

### 2. Verify on PyPI

Visit: https://pypi.org/project/idempotent-middleware/

### 3. Test Installation

```bash
pip install idempotent-middleware
```

## Using API Tokens (Recommended)

To avoid entering credentials every time, configure `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-...your-production-token...

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-...your-test-token...
```

**Security**: Protect this file with appropriate permissions:
```bash
chmod 600 ~/.pypirc
```

Then you can upload without entering credentials:
```bash
twine upload --repository testpypi dist/*  # Test PyPI
twine upload dist/*                          # Production PyPI
```

## Automated Publishing with GitHub Actions

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install build tools
        run: pip install build twine

      - name: Build package
        run: python -m build

      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*
```

Store your PyPI API token as a GitHub secret:
1. Go to repository Settings → Secrets and variables → Actions
2. Add secret: `PYPI_API_TOKEN`
3. Paste your PyPI API token

## Release Checklist

Before each release:

- [ ] All tests passing (`pytest`)
- [ ] Version bumped in `pyproject.toml`
- [ ] CHANGELOG.md updated (create if it doesn't exist)
- [ ] Documentation updated
- [ ] Built and tested on Test PyPI
- [ ] Git tag created: `git tag v0.1.0 && git push origin v0.1.0`
- [ ] Published to production PyPI
- [ ] GitHub release created with release notes

## Troubleshooting

### "File already exists" Error

PyPI doesn't allow re-uploading the same version. You must:
1. Bump the version in `pyproject.toml`
2. Rebuild: `python -m build`
3. Upload the new version

### Import Errors After Installation

Make sure package structure is correct:
```bash
pip show idempotent-middleware  # Check installation details
python -c "import idempotent_middleware; print(idempotent_middleware.__file__)"
```

### Missing Dependencies

Verify `pyproject.toml` lists all required dependencies in the `dependencies` array.

## Post-Publication

After successful publication:

1. **Update README badges**:
   ```markdown
   [![PyPI](https://img.shields.io/pypi/v/idempotent-middleware.svg)](https://pypi.org/project/idempotent-middleware/)
   [![Python Versions](https://img.shields.io/pypi/pyversions/idempotent-middleware.svg)](https://pypi.org/project/idempotent-middleware/)
   ```

2. **Announce** on relevant channels:
   - Twitter/X
   - Reddit (r/Python)
   - Community forums
   - Your blog

3. **Monitor** for issues:
   - GitHub issues
   - PyPI statistics
   - Download counts

## Resources

- [PyPI Help](https://pypi.org/help/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [setuptools Documentation](https://setuptools.pypa.io/)
