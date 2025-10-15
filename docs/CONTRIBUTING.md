# Contributing to PCLink

<div align="center">

![PCLink Icon](docs/assets/pclink_icon.svg)

Thank you for considering contributing to PCLink! This guide will help you get started and ensure contributions remain consistent and high-quality.

</div>

## 🤝 Code of Conduct

Please treat others with respect and professionalism.  
We welcome contributions from developers of all backgrounds and skill levels.

### Our Standards
- Be respectful and kind  
- Be inclusive and helpful to newcomers  
- Provide constructive feedback  
- Be patient with others’ learning pace  

---

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- Git
- Basic knowledge of **Python**, **Web Development**, and **FastAPI**

### Development Setup

1. **Fork & Clone**
   ```bash
   git clone https://github.com/YOUR_USERNAME/pclink.git
   cd pclink
````

2. **Create Virtual Environment**

   ```bash
   python -m venv venv
   source venv/bin/activate       # Linux/Mac
   venv\Scripts\activate          # Windows
   ```

3. **Install Dependencies**

   ```bash
   pip install -e ".[dev]"
   pre-commit install
   ```

4. **Run Tests**

   ```bash
   pytest
   ```

---

## 🛠️ Development Workflow

### 1. Branching

```bash
git checkout -b feature/awesome-feature
# or
git checkout -b fix/bug-description
```

### 2. Make Changes

* Follow code style
* Add docstrings & comments
* Update docs if needed

### 3. Quality Checks

```bash
pytest
black src tests
isort src tests
pre-commit run --all-files
```

### 4. Commit

Use [Conventional Commits](https://www.conventionalcommits.org/):

```bash
git commit -m "feat: add secure device pairing"
```

### 5. Push & PR

```bash
git push origin feature/awesome-feature
```

Then open a Pull Request on GitHub.

---

## 📝 Coding Standards

### Python

* Follow **PEP 8**
* Use type hints
* Keep functions small and focused
* Write docstrings

### Example

```python
class ServerController:
    """Handles server lifecycle and state."""

    def __init__(self, config: dict):
        self.config = config
        self.is_running = False

    def start(self) -> None:
        """Start the server if not already running."""
        if self.is_running:
            raise RuntimeError("Server already running")
        self.is_running = True
```

### GUI

* Use Qt signal/slot properly
* Separate UI and business logic
* Support dark theme & translations

### API

* Follow REST conventions
* Use correct HTTP status codes
* Validate input
* Document endpoints with OpenAPI

---

## 🧪 Testing

### Structure

```
tests/
├── unit/         # Unit tests
├── integration/  # API & workflow tests
├── gui/          # GUI tests
└── fixtures/     # Shared test data
```

### Running

```bash
pytest                  # All tests
pytest tests/unit/      # Unit tests only
pytest --cov=src        # With coverage
```

### Example

```python
def test_server_starts():
    controller = ServerController(config={})
    controller.start()
    assert controller.is_running
```

---

## 🌍 Internationalization

1. Add translations in `gui/localizations.py`
2. Test UI with new language
3. Submit PR with screenshots

Guidelines:

* Keep it concise
* Check layout with long text
* Prefer gender-neutral phrasing

---

## 📚 Documentation

* **Code**: Add docstrings for all public functions/classes
* **User Docs**: Update README for new features
* **API Docs**: Ensure OpenAPI docs are correct
* **Screenshots**: Add when UI changes

---

## 🐛 Bug Reports

### Template

```markdown
**Bug Description**
What went wrong?

**Steps to Reproduce**
1. ...
2. ...

**Expected Behavior**
What should happen?

**Environment**
- OS: Windows 11
- Python: 3.11
- PCLink: 1.2.0
```

---

## 💡 Feature Requests

### Template

```markdown
**Feature**
Short description

**Use Case**
Why it’s useful

**Proposed Solution**
How it could work

**Alternatives**
Other ideas considered
```

---

## 🏷️ Release Process

### Versioning

We follow **Semantic Versioning**:

* `MAJOR`: Breaking changes
* `MINOR`: New features
* `PATCH`: Bug fixes

### Checklist

* [ ] Tests pass
* [ ] Docs updated
* [ ] Version bumped
* [ ] CHANGELOG updated
* [ ] Release notes prepared

---

## 🎯 Contribution Areas

### High Priority

* Mobile app integration
* Security features
* Performance optimizations
* Cross-platform testing

### Medium Priority

* UI/UX improvements
* Plugin architecture
* Translations
* Documentation

### Low Priority

* Refactoring
* Tooling improvements
* Example apps

---

## 📞 Support

* **Issues**: Bug reports & requests
* **Discussions**: Q\&A and ideas
* **Code Review**: All PRs reviewed

---

## 🙏 Recognition

Contributors are credited in:

* README.md
* Release notes
* Documentation

---

<div align="center">

🎉 Thank you for helping improve **PCLink**!

</div>