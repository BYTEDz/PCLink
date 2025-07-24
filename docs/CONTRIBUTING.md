# Contributing to PCLink

Thank you for your interest in contributing to PCLink! We welcome contributions from the community and are pleased to have you join us.

## 🤝 Code of Conduct

This project and everyone participating in it is governed by our Code of Conduct. By participating, you are expected to uphold this code.

### Our Standards

- **Be respectful**: Treat everyone with respect and kindness
- **Be inclusive**: Welcome newcomers and help them get started
- **Be constructive**: Provide helpful feedback and suggestions
- **Be patient**: Remember that everyone has different skill levels

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- Git
- Basic knowledge of Python, Qt/PySide6, and FastAPI

### Development Setup

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/bYTEDz/pclink.git
   cd pclink
   ```

3. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

5. **Run tests** to ensure everything works:
   ```bash
   python run_tests.py
   ```

## 🛠️ Development Workflow

### 1. Create a Branch

Create a new branch for your feature or bug fix:
```bash
git checkout -b feature/your-feature-name
# or
git checkout -b bugfix/issue-description
```

### 2. Make Changes

- Write clean, readable code
- Follow the existing code style
- Add comments for complex logic
- Update documentation if needed

### 3. Test Your Changes

```bash
# Run all tests
python run_tests.py

# Run specific tests
python test_startup_comprehensive.py
python test_state_transfer.py

# Test the application manually
python main.py
python main.py --startup
```

### 4. Commit Your Changes

Write clear, descriptive commit messages:
```bash
git add .
git commit -m "Add feature: description of what you added"
```

### 5. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub with:
- Clear title and description
- Reference any related issues
- Screenshots if UI changes are involved

## 📝 Coding Standards

### Python Style Guide

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use meaningful variable and function names
- Keep functions focused and small
- Add docstrings for classes and functions

### Code Organization

```python
# Good example
class ServerController:
    """Manages server lifecycle and state."""
    
    def __init__(self, config):
        """Initialize controller with configuration."""
        self.config = config
        self.is_running = False
    
    def start_server(self):
        """Start the API server."""
        if self.is_running:
            raise RuntimeError("Server is already running")
        # Implementation here
```

### GUI Development

- Use Qt's signal/slot mechanism properly
- Separate UI logic from business logic
- Make UI responsive and accessible
- Test on different screen sizes and themes

### API Development

- Follow REST conventions
- Use appropriate HTTP status codes
- Validate input data
- Handle errors gracefully
- Document endpoints clearly

## 🧪 Testing Guidelines

### Writing Tests

- Write tests for new features
- Test both success and failure cases
- Use descriptive test names
- Keep tests independent and isolated

### Test Categories

1. **Unit Tests**: Test individual functions/classes
2. **Integration Tests**: Test component interactions
3. **GUI Tests**: Test user interface components
4. **API Tests**: Test REST endpoints

### Example Test

```python
def test_server_startup():
    """Test that server starts correctly in headless mode."""
    controller = ServerController(test_config)
    
    # Test successful startup
    controller.start_server()
    assert controller.is_running is True
    
    # Test cleanup
    controller.stop_server()
    assert controller.is_running is False
```

## 🌍 Internationalization

### Adding New Languages

1. Edit `gui/localizations.py`
2. Add your language code and translations
3. Test the UI with your language
4. Update the README with the new language

### Translation Guidelines

- Keep translations concise but clear
- Consider cultural context
- Test UI layout with longer translations
- Use gender-neutral language when possible

## 📚 Documentation

### Code Documentation

- Add docstrings to all public functions and classes
- Use clear, concise language
- Include parameter and return value descriptions
- Add usage examples for complex functions

### User Documentation

- Update README.md for new features
- Add API documentation for new endpoints
- Include screenshots for UI changes
- Write clear setup and usage instructions

## 🐛 Bug Reports

### Before Reporting

1. Check if the issue already exists
2. Try to reproduce the bug
3. Test with the latest version
4. Gather relevant information

### Bug Report Template

```markdown
**Bug Description**
A clear description of what the bug is.

**Steps to Reproduce**
1. Go to '...'
2. Click on '....'
3. See error

**Expected Behavior**
What you expected to happen.

**Screenshots**
If applicable, add screenshots.

**Environment**
- OS: [e.g. Windows 10]
- Python Version: [e.g. 3.9.0]
- PCLink Version: [e.g. 1.0.0]
```

## 💡 Feature Requests

### Before Requesting

1. Check if the feature already exists
2. Search existing feature requests
3. Consider if it fits the project scope
4. Think about implementation complexity

### Feature Request Template

```markdown
**Feature Description**
A clear description of the feature you'd like to see.

**Use Case**
Explain why this feature would be useful.

**Proposed Solution**
Describe how you think this could be implemented.

**Alternatives**
Any alternative solutions you've considered.
```

## 🏷️ Release Process

### Version Numbers

We use [Semantic Versioning](https://semver.org/):
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Release Checklist

- [ ] All tests pass
- [ ] Documentation updated
- [ ] Version number bumped
- [ ] Changelog updated
- [ ] Release notes prepared

## 🎯 Areas for Contribution

### High Priority

- [ ] Mobile companion app development
- [ ] Enhanced error handling and logging
- [ ] Performance optimizations
- [ ] Security improvements
- [ ] Cross-platform testing

### Medium Priority

- [ ] Plugin system architecture
- [ ] Additional language translations
- [ ] UI/UX improvements
- [ ] Documentation enhancements
- [ ] Test coverage improvements

### Low Priority

- [ ] Code refactoring
- [ ] Build system improvements
- [ ] Development tooling
- [ ] Example applications

## 📞 Getting Help

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For questions and general discussion
- **Code Review**: We provide constructive feedback on all PRs

## 🙏 Recognition

Contributors will be recognized in:
- README.md contributors section
- Release notes
- Project documentation

Thank you for contributing to PCLink! 🎉