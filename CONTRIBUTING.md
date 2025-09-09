# Contributing to PCLink

<div align="center">

![PCLink Icon](docs/assets/pclink_icon.svg)

💻 Thank you for considering contributing to **PCLink**!  
This guide explains how to set up your environment, follow coding standards, and submit high-quality contributions.

</div>

---

## 📜 Code of Conduct
Be respectful and collaborative. Contributions from all skill levels are welcome.  
We follow a **professional, inclusive, and constructive** approach in code reviews and discussions.

---

## 🚀 Getting Started

### Prerequisites
- Python **3.8+**
- Git
- [PySide6/Qt](https://doc.qt.io/qtforpython/) knowledge for GUI work
- [FastAPI](https://fastapi.tiangolo.com/) knowledge for API work

### Setup Environment
```bash
# Clone your fork
git clone https://github.com/<your-username>/pclink.git
cd pclink

# Create venv
python -m venv venv
source venv/bin/activate   # macOS/Linux
venv\Scripts\activate      # Windows

# Install dev dependencies
pip install -e ".[dev]"
pre-commit install

# Verify
python -m pclink
pytest
````

---

## 🛠️ Development Workflow

1. **Create a Branch**

   ```bash
   git checkout -b feature/your-feature
   ```
2. **Make Changes & Test**

   ```bash
   python -m pclink                    # Run app
   python scripts/build.py --debug     # Test build
   ```
3. **Quality Checks**

   ```bash
   pytest
   black src tests
   isort src tests
   pre-commit run --all-files
   ```
4. **Commit & Push**

   ```bash
   git add .
   git commit -m "feat: short description"
   git push origin feature/your-feature
   ```

---

## 📝 Commit Guidelines

Follow [Conventional Commits](https://www.conventionalcommits.org/):

* `feat:` → new feature
* `fix:` → bug fix
* `docs:` → documentation only
* `style:` → formatting, no logic change
* `refactor:` → restructuring code
* `test:` → add/update tests
* `chore:` → tooling, maintenance

---

## 🔄 Pull Requests

* ✅ Pass tests and lint checks
* ✅ Update docs if needed
* ✅ Add entry to **CHANGELOG.md**
* ✅ Keep PRs focused (one topic per PR)

---

## 📐 Coding Standards

### Python

* **PEP 8** style (auto-enforced with Black & isort)
* Use **type hints** and **docstrings**
* Catch **specific exceptions**

### GUI (Qt/PySide6)

* Follow app’s **dark theme**
* Support **different screen sizes**
* Use **Qt accessibility guidelines**
* Add strings to `localizations.py`

### API (FastAPI)

* Use **routers per module**
* Add OpenAPI docs with request/response models
* Validate inputs & enforce auth
* Return consistent error formats

---

## 🧪 Testing

### Structure

```
tests/
├── unit/          # Functions/classes
├── integration/   # API endpoints
├── gui/           # UI tests
└── fixtures/      # Reusable test data
```

### Running

```bash
pytest                 # All tests
pytest tests/unit/     # Unit only
pytest tests/integration/
pytest --cov=src       # With coverage
```

### Guidelines

* Unit tests → small, isolated
* Integration tests → workflows & API
* GUI tests → user interactions
* Mock external dependencies

---

## 🎯 Contribution Areas

### High Priority

* Mobile ↔ PC integration
* Performance optimizations
* Security improvements
* Cross-platform validation

### Medium

* File/media features
* UI/UX refinements
* Docs & guides
* More localizations

### Good First Issues

* Minor bug fixes
* Documentation updates
* Add missing tests
* Code cleanup

---

## 📦 Release Process (Maintainers Only)

1. Bump version:

   ```bash
   python scripts/release.py --version X.Y.Z
   ```
2. Update `CHANGELOG.md`
3. Push tag & create GitHub release
4. Verify CI builds & published artifacts

### Versioning

* **Major (X.0.0)** → breaking changes
* **Minor (X.Y.0)** → features, backward compatible
* **Patch (X.Y.Z)** → bug fixes

---

## 📖 Documentation

* Keep README & docs updated with new features
* Add API/OpenAPI docs where applicable

---

## 📜 License

By contributing, you agree your code will be licensed under **AGPLv3** (default project license).
