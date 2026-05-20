# crease

Declarative Excel-to-JSON extraction and validation. A YAML template describes where the data lives and what the fields mean; the same template drives both extraction (cells → canonical JSON) and validation (constraints → structured errors).

## First principles

1. **Documentation first.** Every API change is paired with a `docs/` update in the same PR. A PR without docs is incomplete. The `docs/` directory is the source of truth for what the library does and why. Code examples in docs must be real — if a snippet is shown, it must execute as written.

2. **Docs are the product.** Write for the data engineer who has never seen this library. No internal jargon without definition. The README is a hook that sells the value and links into the docs site; the docs site is the manual. Anecdotes (`docs/why.md`) carry the *why* — every guide page can pull a relevant one as an "in the wild" callout so the connection between failure mode and feature stays visible.

3. **Pydantic-native vocabulary.** Errors, validation, and projection use the names a Python dev already knows from Pydantic: `ValidationError`, `errors()`, `error_count()`, `loc`, `type`, `msg`, `input`, `ctx`. No bespoke terminology where a standard one fits. A DE who used Pydantic this year should read the crease API and immediately know how to use it.

4. **Fail loudly with coordinates.** The library's whole pitch is that Excel failures get surfaced with row and field coordinates, never swallowed into the canonical output. Default behavior on any projection method (`to_pydantic`, `to_pandas`, `iter`, `stream`) is to **halt** if extraction produced errors. Opportunistic recovery requires the explicit `allow_partial=True` opt-in.

5. **No surprise dependencies.** `crease.extract` returns a plain dict — pandas and pydantic are only imported when `to_pandas` / `to_pydantic` is actually called. Someone who only wants canonical JSON shouldn't pay an import cost for adapters they don't use.

## Repository organization

The target layout follows modern Python convention (`src/` layout, used by pydantic, httpx, requests, FastAPI). No loose `.py` files at the repo root.

```
src/
  crease/                    Installed package — what `pip install crease` ships
    __init__.py
    extractor.py
    validator.py
    ...
tests/                       Pytest suite
test_cases/                  Labeled fixture corpus (doubles as spec)
docs/                        MkDocs site (source of truth for behavior)
tools/                       Dev tooling, NOT shipped to PyPI
  inferrer/                  Streamlit app + schema_inference module
  fixturegen/                Synthetic-xlsx generator (generate, corruptors,
                             layouts, evaluator, profiler, scorer, series, sheet)
pyproject.toml
README.md
CLAUDE.md
```

**Rules:**

- **No flat `.py` files at the repo root.** Everything belongs to the package (`src/crease/`), a test (`tests/`), the docs (`docs/`), or a tool (`tools/<subdir>/`). If a new file doesn't have an obvious home, that's a signal to think about what it is before adding it.
- **`src/` layout is mandatory.** Forces `pip install -e .` for dev, which catches packaging bugs early (you can't accidentally import from the local source tree without installing).
- **`tools/` is not on the install path.** Anything under `tools/` is for developing crease, not for shipping with crease. The streamlit inferrer is a dev convenience and reference UI, not a library entry point — if it ever becomes a user-facing CLI command, it moves into `src/crease/inferrer/`.
- **One purpose per top-level directory.** Don't create a `utils/`, `lib/`, `common/`, or `misc/` dumping ground. Shared code lives where its primary user lives.

## Documentation

Built with **MkDocs Material + mkdocstrings**. Same stack as Pydantic, FastAPI, HTTPX — the conventions a Python dev expects.

```
docs/
  index.md                   Landing — what crease is, the 30-second pitch
  why.md                     Anecdotes catalog with sources; the "why this exists" page
  quickstart.md              Three-step extract → validate → project flow
  guides/
    templates.md             Authoring a template
    layouts.md               flat / property_sheet / anchored / multi-tab
    streaming.md             Big files
    pydantic-projection.md   to_pydantic, opportunistic field matching, model rules
    pandas-projection.md     to_pandas
  reference/
    extract.md               ::: crease.extract  (auto-rendered from docstrings)
    validate.md
    template.md
    errors.md
  cli.md
  conventions.md             Excel patterns we handle (mirrors CONVENTIONS.md at root)
mkdocs.yml
```

**Docstrings are Google-style** — parses cleanly in mkdocstrings, readable in editors, no reST learning curve:

```python
def extract(source: str | Path, template: Template) -> ExtractResult:
    """Apply a template to an xlsx file and return canonical JSON.

    Args:
        source: Path to the .xlsx file.
        template: A loaded `Template` instance.

    Returns:
        An `ExtractResult` whose `.canonical` holds the dict of entities.

    Raises:
        crease.TemplateError: If the template is malformed.
    """
```

**Every public function, class, and method has a docstring.** Private (`_`-prefixed) ones are optional.

**Code examples in docs must execute.** Either as doctests (`pytest --doctest-glob='docs/**/*.md'`) or as runnable scripts under `docs/examples/` that CI executes. A snippet that lies because the API drifted is worse than no snippet.

**No emojis in docs or docstrings.**

## Code comments: brief by default

Default to writing no comments. Only add one when the **why** is non-obvious — a hidden constraint, a workaround for a specific upstream quirk (Excel's date-autoconvert, openpyxl's empty-row handling), behavior that would surprise a reader.

- One short line is the target. Multi-paragraph essays on a 5-line function are noise.
- Never describe **what** the code does. Identifiers and short functions do that.
- Don't reference the current task or PR ("added for the v0.3 release"). The commit message owns that.
- Don't list rejected alternatives. That belongs in the PR body.

Docstrings are a separate concern from inline comments — those are mandatory on public APIs (see Documentation above), brief by default everywhere else.

## Commits

Project uses [Conventional Commits](https://www.conventionalcommits.org/) and `python-semantic-release` for automated versioning (already wired in `pyproject.toml`).

```
type(scope): description
```

**Release-triggering:** `feat` (minor), `fix` / `perf` / `refactor` / `revert` (patch).
**No release:** `docs`, `style`, `test`, `build`, `ci`, `chore`.
**Breaking:** `!` after type or `BREAKING CHANGE:` footer → major bump.

Examples:
```
feat(extractor): add allow_partial flag to to_pydantic
fix(validator): emit wrong_type with likely_cause for Excel date autoconvert
docs(why): add JPMorgan VaR copy-paste anecdote with sources
```

## API stability notes

Surface area to keep coherent (any change here ripples through docs + tests):

- `crease.extract`, `crease.validate`, `crease.check`, `crease.stream`, `crease.open`
- `crease.Template`, `crease.ExtractResult`, `crease.Report`, `crease.Error`, `crease.ValidationError`
- Projection methods: `.canonical`, `.iter()`, `.get()`, `.to_pydantic()`, `.to_pandas()`
- Symmetric `model=` and `allow_partial=` kwargs across all projection / stream paths
- Error reason codes (the `error.type` taxonomy in the README) are part of the public contract — adding new codes is a `feat`, renaming or removing is `BREAKING CHANGE`.
