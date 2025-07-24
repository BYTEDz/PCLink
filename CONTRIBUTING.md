# Contributing to PCLink

<div align="center">

![PCLink Icon](docs/assets/pclink_icon.svg)

Thank you for considering contributing to PCLink! This document provides guidelines and instructions for contributing to this project.

</div>

## Code of Conduct

Please be respectful and considerate of others when contributing to this project. We welcome contributions from developers of all skill levels.

## Getting Started

### Prerequisites
- Python 3.8 or higher
- Git
- Basic knowledge of Qt/PySide6 for GUI contributions
- FastAPI knowledge for API contributions

### Setup Development Environment

1. **Fork and Clone**
   ```bash
   git clone https://github.com/yourusername/pclink.git
   cd pclink
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Unix/macOS
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -e ".[dev]"
   pre-commit install
   ```

4. **Verify Installation**
   ```bash
   python -m pclink  # Should start the application
   pytest            # Should run tests successfully
   ```

## Development Workflow

### Making Changes

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/bug-description
   ```

2. **Development Process**
   ```bash
   # Make your changes
   python -m pclink                    # Test your changes
   python scripts/build.py --debug     # Test build process
   ```

3. **Quality Checks**
   ```bash
   pytest                              # Run tests
   black src tests                     # Format code
   isort src tests                     # Sort imports
   pre-commit run --all-files         # Run all checks
   ```

4. **Commit and Push**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   git push origin feature/your-feature-name
   ```

### Commit Message Format
Use conventional commits format:
- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation changes
- `style:` for formatting changes
- `refactor:` for code refactoring
- `test:` for adding tests
- `chore:` for maintenance tasks

## Pull Request Process

1. Ensure your code passes all tests and linting
2. Update documentation if necessary
3. Update the CHANGELOG.md file with details of your changes
4. Your pull request will be reviewed by maintainers

## Coding Standards

### Python Code Style
- **PEP 8**: Follow Python style guidelines (enforced by black)
- **Type Hints**: Use type hints for function parameters and return values
- **Docstrings**: Write comprehensive docstrings for all public functions and classes
- **Error Handling**: Use proper exception handling with specific exception types

### Qt/GUI Guidelines
- **Theme Consistency**: Use the app's dark theme styling
- **Responsive Design**: Ensure UI works across different screen sizes
- **Accessibility**: Follow Qt accessibility guidelines
- **Localization**: Add translation strings to `localizations.py`

### API Development
- **FastAPI Standards**: Follow FastAPI best practices
- **Documentation**: Use proper OpenAPI documentation
- **Security**: Validate all inputs and use proper authentication
- **Error Responses**: Return consistent error response formats

## Testing

### Test Structure
```
tests/
├── unit/           # Unit tests for individual components
├── integration/    # Integration tests for API endpoints
├── gui/           # GUI-specific tests
└── fixtures/      # Test data and fixtures
```

### Running Tests
```bash
pytest                              # Run all tests
pytest tests/unit/                  # Run unit tests only
pytest tests/integration/          # Run integration tests
pytest --cov=src                   # Run with coverage
```

### Writing Tests
- **Unit Tests**: Test individual functions and classes
- **Integration Tests**: Test API endpoints and workflows
- **GUI Tests**: Test user interface components (when applicable)
- **Mock External Dependencies**: Use mocks for external services

## Areas for Contribution

### High Priority
- **Mobile App Integration**: Improve mobile app communication
- **Performance Optimization**: Optimize server response times
- **Security Enhancements**: Additional security features
- **Cross-Platform Testing**: Test on different operating systems

### Medium Priority
- **New Features**: File transfer improvements, media controls
- **UI/UX Improvements**: Better user interface design
- **Documentation**: User guides, API documentation
- **Localization**: Additional language translations

### Good First Issues
- **Bug Fixes**: Small bug fixes and improvements
- **Documentation**: README updates, code comments
- **Testing**: Add tests for existing functionality
- **Code Cleanup**: Refactoring and code organization

## Release Process

### For Maintainers
1. **Update Version**: Use `python scripts/release.py --version X.Y.Z`
2. **Review Changes**: Ensure CHANGELOG.md is updated
3. **Create Release**: Script automatically creates Git tag and GitHub release
4. **Monitor Build**: GitHub Actions builds and publishes artifacts

### Version Numbering
- **Major (X.0.0)**: Breaking changes, major new features
- **Minor (X.Y.0)**: New features, backward compatible
- **Patch (X.Y.Z)**: Bug fixes, small improvements

## Documentation

- Update documentation for any changes to functionality
- Document new features in the appropriate section

## License

By contributing to PCLink, you agree that your contributions will be licensed under the project's license.