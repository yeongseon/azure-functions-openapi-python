# Changelog

All notable changes to this project will be documented in this file.
## [0.19.0] - 2026-06-06

### Bug Fixes

- *(spec)* Accept OpenAPI wildcard range codes (2XX–5XX) in _valid_response_status (#241) 
- Address all OpenAPI spec quality gaps — validation, decorator order, and spec correctness 
- *(docs)* Correct remaining decorator stacking order in PRD, index, troubleshooting, and docstring 
- *(docs)* Correct @openapi + @app.route stacking order in examples and docs 
- *(spec)* Detect duplicate path+method and expand _validate_spec checks 
- *(decorator)* Raise on ambiguous multi-method binding 
- *(readme)* Correct Codecov badge URL (remove duplicate -python suffix) 
- *(spec)* Add strict raise, 3.0 compat check, and inline 3.1 schema conversion 
- *(decorator)* Add type-specific security scheme field validation 
- *(decorator)* Validate and normalize HTTP method in @openapi (#222) 
- *(spec)* Add path parameter and operationId validation (#225) 
- *(security)* Use proper JS/HTML escaping in Swagger UI (#221) 

### Documentation

- *(agents)* Mandate issue-first workflow before opening PRs 
- *(deployment)* Add real Azure deployment screenshots (#230) 

### Features

- *(spec)* Change default OpenAPI version to 3.1 (#229) 
- *(decorator)* Auto-detect route/method from FunctionBuilder (#226) 
- *(spec)* Add strict mode for fail-fast on malformed entries (#224) 

### Miscellaneous Tasks

- *(deps)* Add openapi-spec-validator>=0.7.0 to dev extras 
- *(deps)* Bump ruff from 0.15.12 to 0.15.15 (#228) 
- *(deps)* Bump github/codeql-action from 4.35.2 to 4.36.1 (#227) 
- *(deps)* Bump actions/stale from 10.2.0 to 10.3.0 (#210) 
- *(deps)* Bump codecov/codecov-action from 6.0.0 to 6.0.1 (#207) 

### Other

- Bump version to 0.19.0 
## [0.18.2] - 2026-05-23

### Bug Fixes

- *(decorator)* Guard FunctionBuilder._function._func access with actionable error 

### Documentation

- Update changelog 

### Other

- Bump version to 0.18.2 
## [0.18.1] - 2026-05-14

### Documentation

- Update changelog 
- Fix ecosystem table names, badges, and Part of intro line 
- Mark cookbook as dogfood, fix ecosystem table description 
- Fix ecosystem table — add knowledge row, fix labels and links 
- *(agents)* Add Issue Conventions section to AGENTS.md 

### Miscellaneous Tasks

- *(deps)* Bump mypy from 1.20.2 to 2.1.0 
- *(release)* Fix changelog template and decouple version test from literals 

### Other

- Bump version to 0.18.1 

### Styling

- *(tests)* Sort imports in test_bridge.py 

### Testing

- Raise coverage to 95%+ and enforce via AGENTS.md and pyproject.toml 
## [0.18.0] - 2026-04-26

### Bug Fixes

- *(swagger-ui)* Pin swagger-ui-dist CDN version (#191) (#196) 
- Resolve `openapi` package attribute to the decorator (#187) (#188) 

### Documentation

- Update changelog 
- Add Request Flow and Runtime Relationship section to architecture 
- Align all documentation with redesigned examples (#176) 

### Features

- *(cli)* Expose --description option for generated OpenAPI info (#200) 
- *(route-prefix)* Make Azure Functions route prefix configurable (#193) (#197) 
- Harden metadata convention reader (#172) (#178) 
- Replace examples with practical, production-ready patterns (#173) 

### Miscellaneous Tasks

- *(deps)* Bump ruff from 0.15.10 to 0.15.12 (#185) 
- *(deps)* Bump mypy from 1.20.1 to 1.20.2 (#186) 
- Fix project metadata URLs to match the actual repository (#195) 
- *(deps)* Bump softprops/action-gh-release from 2.6.1 to 3.0.0 
- *(deps)* Bump github/codeql-action from 4.35.1 to 4.35.2 
- *(deps)* Bump actions/github-script from 8.0.0 to 9.0.0 
- *(deps)* Bump actions/upload-artifact from 7.0.0 to 7.0.1 
- *(deps)* Bump mypy from 1.20.0 to 1.20.1 

### Other

- Bump version to 0.18.0 

### Refactor

- *(spec)* Rename internal openapi.py submodule to spec.py (#194) (#202) 
- Remove legacy _azure_functions_toolkit_metadata fallback from bridge (#177) 

### Testing

- Bump expected __version__ to 0.18.0 ahead of release-minor 
- *(bridge)* Cover substring-trap regression for route prefix matching (#199) 
## [0.17.1] - 2026-04-10

### Documentation

- Update changelog 
- Add Before/After section to README (#167) 
- Standardize ecosystem table in README 

### Miscellaneous Tasks

- Bump ruff from 0.15.8 to 0.15.10 (#164) 
- *(deps)* Bump softprops/action-gh-release from 2.2.2 to 2.6.1 (#160) 
- *(deps)* Bump ruff from 0.15.8 to 0.15.9 (#161) 

### Other

- Bump version to 0.17.1 

### Refactor

- Rename metadata attr to _azure_functions_metadata (#171) 
## [0.17.0] - 2026-04-07

### Bug Fixes

- Resolve MkDocs strict-mode failures for nav and links (#154) (#155) 

### Documentation

- Update changelog 
- Add llms.txt for LLM-friendly documentation (#156) (#157) 

### Features

- Add scan_validation_metadata bridge for zero-duplication OpenAPI (#158) 

### Other

- Bump version to 0.17.0 

### Refactor

- Decouple bridge from azure-functions-validation via convention-based metadata 

### Testing

- Update version assertion to 0.17.0 for upcoming release 
## [0.16.0] - 2026-04-06

### Bug Fixes

- Apply Oracle PR review — terminology alignment 
- Switch Mermaid fence format to fence_div_format for rendering 

### Documentation

- Remove duplicate SUBSCRIPTION_ID assignment in Example 2 
- Rewrite deployment guide for developer-friendly Azure Functions experience 
- Add Azure deployment verification note to README (#150) 
- Add Azure-verified sample output to README (#149) 
- Add deployment guide for OpenAPI examples (#147) 
- Align ecosystem positioning and document programmatic integration API 
- Enable Mermaid diagram rendering on GitHub Pages 
- Standardize architecture docs with Mermaid diagrams, Sources, See Also 
- Add release process to AGENTS.md 

### Features

- Add register_openapi_metadata() programmatic API for v0.16.0 (#144) 

### Miscellaneous Tasks

- *(deps)* Bump codecov/codecov-action from 5.5.3 to 6.0.0 (#130) 
- *(deps)* Bump github/codeql-action from 4.34.1 to 4.35.1 (#129) 
- *(deps)* Bump mypy from 1.19.1 to 1.20.0 (#132) 
- *(deps)* Bump ruff from 0.15.7 to 0.15.8 (#131) 
- Add automatic GitHub Release creation on tag push (#128) 

### Testing

- Align with_validation snapshots with 201 response schema (#134) 
## [0.15.1] - 2026-03-29

### Documentation

- Sync docs/changelog.md with 0.15.0 release notes (#126) 
- Fix README Quick Start to wrap OpenAPI helpers in HttpResponse (#125) 
- Update README with Azure Functions Python DX Toolkit branding 

### Miscellaneous Tasks

- Release v0.15.1 
- *(deps)* Bump ruff from 0.15.6 to 0.15.7 (#124) 
- *(deps)* Bump anchore/sbom-action from 0.23.1 to 0.24.0 (#123) 
- *(deps)* Bump github/codeql-action from 4.33.0 to 4.34.1 (#122) 
- Add .venv-review-cli/ to .gitignore and set environment to pypi 
- Use standard pypi environment name for Trusted Publisher 
- Rename publish environment from production to release 
- Unify CI/CD workflow configurations 
## [0.15.0] - 2026-03-21

### Bug Fixes

- Apply response_model schema to first declared success response (#114) 
- Add --no-cov and pytest-html artifact to e2e workflow 
- Replace redundant mypy overrides+exclude with overrides only 

### Documentation

- Add real Azure e2e test section to testing.md and CHANGELOG 

### Features

- Add unified requests/responses decorator parameters (#115) 
- Add real Azure e2e tests and CI workflow 
- Drop Pydantic v1 support, require pydantic>=2.0,<3.0 

### Miscellaneous Tasks

- Release v0.15.0 
- Remove AGENT.md refs from AGENTS.md, standardize .gitignore (#117) 
- Fix ruff version, coverage threshold, pre-commit refs, remove orphan labels workflow (#116) 
- *(deps)* Bump anchore/sbom-action from 0.23.0 to 0.23.1 (#104) 
- *(deps)* Update mkdocstrings[python] requirement from <1.0 to <2.0 (#106) 
- *(deps)* Bump codecov/codecov-action from 5.5.2 to 5.5.3 (#110) 
- *(deps)* Bump ruff from 0.15.5 to 0.15.6 (#111) 
- *(deps)* Bump github/codeql-action from 4.32.6 to 4.33.0 (#112) 
- *(deps)* Bump azure/login from 2.3.0 to 3.0.0 (#113) 
- Trigger e2e only on release tag push (v*) 
- Upgrade GitHub Actions to Node.js 24 compatible versions 
- Enforce coverage fail_under = 96 
- Add keywords to pyproject.toml 
- Add AGENTS.md, Typing classifier, test_public_api, Dev Status 4-Beta, .venv-review in .gitignore 
## [0.14.0] - 2026-03-15

### Bug Fixes

- Improve openapi spec generation and logging 
- Enhance CLI error handling 
- Improve decorator imports and deepcopy usage 
- Enhance utils validation and error handling 
- Implement --pretty flag, extract _build_spec helper, sync docs 
- Use stable action tags in label-sync workflow 

### Documentation

- Add CLI quick-start to README, improve Troubleshooting, add Pydantic v2 edge case tests 
- Add codex agent guidance 

### Features

- Separate exceptions into dedicated module 
- Add --app module import option and empty-paths guard to CLI 

### Other

- Bump version to 0.14.0 

### Refactor

- *(openapi)* Extract _ensure_default_response helper and add unit tests 

### Testing

- Add snapshot regression tests 
## [0.13.1] - 2026-03-14

### Bug Fixes

- Move dependencies out of [project.urls] section in pyproject.toml 
- Update mock assertions to match security_schemes parameter addition 
- Resolve E501 line-too-long lint error in test 
- Use repository-relative image paths in localized READMEs 
- *(lint)* Fix import sort order in with_validation test 
- *(tests)* Skip with_validation tests when azure-functions-validation not installed 
- *(mypy)* Skip type-checking examples imported via tests 

### Documentation

- Overhaul documentation to production quality 
- Sync translated READMEs (ko, ja, zh-CN) with English 
- Unify README — Title Case H1, add Why Use It and Ecosystem, reorder sections 
- Add example-first design section to PRD 
- Fix stale tool versions in development.md 
- Fix broken code blocks with complete function bodies 
- Expand all documentation pages to production quality 
- Remove emojis from documentation and cliff.toml 
- Sync Release badge to translated READMEs 
- Refine localized README language switcher 
- Add localized README translations 
- *(readme)* Move disclaimer before license section 
- *(readme)* Add Microsoft trademark disclaimer 
- Document request and response schemas in quick start 
- Keep the quick start simple without pydantic 
- Keep the quick start concise and working 

### Features

- Add components.securitySchemes support (closes #81) 
- *(examples)* Add with_validation example showing openapi and validation integration 

### Miscellaneous Tasks

- Add classifiers and project.urls to pyproject.toml 
- Update pre-commit hook versions and unify forbid-korean targets 

### Other

- Bump version to 0.13.1 

### Refactor

- *(examples)* Rename hello_openapi to hello and todo_crud_api to todo_crud 

### Styling

- Unify tooling — remove black, standardize pre-commit and Makefile 
## [0.12.1] - 2026-03-09

### Bug Fixes

- Improve request_model/response_model validation with helpful error messages 

### Documentation

- Use working example 

### Miscellaneous Tasks

- Bump version to 0.12.1 
- Publish releases through the production environment 
- Use the stable trusted publishing action ref 
- Use trusted publishing for releases 

### Styling

- Fix line length in error messages 
## [0.12.0] - 2026-03-08

### Bug Fixes

- Support FunctionBuilder inputs in decorator 
- Normalize generated route paths 
- Make sure that all paths have a leading slash 
- Include api server 
- Limit default response fallback to empty responses 
- Include default 200 response 
- Allow dependabot branch names 

### Documentation

- Update changelog for 0.12.0 
- Remove the VHS demo from openapi 
- Remove the final terminal snapshot from the demo 
- Add a generated spec preview to the openapi demo 
- Run the representative example in the openapi demo 
- Standardize repository planning documents 
- Slow down openapi demo and add final snapshot 
- Fix openapi demo rendering workflow 
- Use workspace-based openapi demo setup 
- Simplify Swagger preview capture 
- Expand Swagger UI preview endpoint 
- Automate Swagger UI preview generation 
- Clarify README demo outcomes 
- Show web preview in README demo 
- Show generated OpenAPI output in demo 
- Simplify VHS README demo scenario 
- Add VHS README demo 
- Document openapi example policy 
- Classify openapi example coverage roles 
- Position openapi for Azure Functions Python v2 
- Improve development guide with prerequisites, workflow, and full Makefile reference 
- Add release process guide 

### Features

- Allow custom OpenAPI info description 

### Miscellaneous Tasks

- Support manual openapi releases 
- Ci: 
- Pin openapi docs dependencies 
- Align openapi docs dependencies 
- Align openapi maintenance workflows 
- *(openapi)* Format 
- Apply remaining dependabot updates 
- *(deps)* Bump actions/upload-artifact from 6.0.0 to 7.0.0 
- *(deps)* Bump bandit from 1.9.3 to 1.9.4 
- *(deps)* Bump ruff from 0.14.14 to 0.15.5 
- Align tooling and repository maintenance 
- Add git-cliff configuration and remove git-changelog dependency 

### Other

- Harden release automation 
- Bump version to 0.12.0 
- Fix explicit version releases 

### Testing

- Raise openapi coverage for cli and utils 
- Cover todo CRUD example app 
## [0.10.1] - 2026-02-10

### Documentation

- Update changelog 
- Expand example setup guidance 
- Remove authentication example 

### Miscellaneous Tasks

- *(examples)* Align requirements 

### Other

- Bump version to 0.10.1 
## [0.10.0] - 2026-02-09

### Bug Fixes

- *(decorator)* Preserve validation errors 
- *(openapi)* Drop error utilities 
- *(metrics)* Use PerformanceMonitor response-time average 
- *(security)* Harden Swagger UI CSP and gate client logging 
- *(validation)* Disallow whitespace in route paths 
- *(validation)* Align fallback logs with strict behavior 
- *(openapi)* Preserve explicit 200 response when response_model exists 
- *(test)* Satisfy mypy type for security validation case 
- *(ci)* Resolve lint and deploy workflow validation errors 

### Documentation

- Update changelog 
- Fix mkdocs nav and links 
- Align changelog with cleanup 
- Refresh contributing guidance 
- Link to canonical root docs 
- Trim api reference notes 
- Merge swagger ui config into usage 
- Drop tutorials page 
- Remove redundant examples and guides 
- Drop non-http examples 
- Remove internal operations guides 
- Normalize doc casing and links 
- Align quality metrics and Python support policy 
- Clarify supported Python versions in README 
- Add comprehensive examples, tutorials, and configuration guide (#67) 
- Remove links to missing pages 
- Improve core documentation (index, usage, api, installation, README) 
- Fix CI badge workflow and tool versions 
- Fix CI badge workflow and tool versions 
- Add governance, design principles, and LSP configuration 

### Features

- Resolve deployment and OpenAPI security issue backlog 

### Miscellaneous Tasks

- *(lint)* Drop unused imports 
- *(docs)* Remove monitoring references 
- *(docs)* Remove performance guide and related artifacts 
- Remove caching layer and update docs 
- *(cli)* Remove validate command and document external validator 
- Remove monitoring modules and CLI commands 
- Remove monitoring utilities and update docs 
- Remove redundant scripts directory 
- *(ci)* Pin GitHub Actions to immutable SHAs 
- Ignore local oh-my-opencode config 
- *(ci)* Route Bandit scans through Makefile security target 
- *(deps)* Bump GitHub Actions versions in workflows 
- *(deps)* Bump actions/setup-python from 4 to 6 
- Skip codecov on dependabot (#80) 
- Add maintenance workflows and automation (#70) 
- Configure dependabot for automated dependency updates (#72) 
- Add release process and versioning documentation (#71) 
- Add performance monitoring and regression testing (#69) 
- Add security policies and incident response (#68) 
- *(deps)* Bump ruff from 0.11.13 to 0.14.13 
- *(deps)* Bump mypy from 1.15.0 to 1.19.1 
- *(deps)* Bump bandit from 1.8.3 to 1.9.3 
- *(deps)* Bump black from 25.1.0 to 26.1.0 
- *(deps)* Bump actions/checkout from 4 to 6 
- *(deps)* Bump github/codeql-action from 3 to 4 
- *(deps)* Bump codecov/codecov-action from 4 to 5 
- *(deps)* Bump actions/setup-python from 5 to 6 

### Other

- Bump version to 0.10.0 

### Refactor

- Harden registry and runtime state handling 
- Simplify branch strategy to GitHub Flow 
## [0.8.0] - 2026-01-22

### Documentation

- Improve security policy with GitHub Security Advisory 

### Features

- Add optional OpenAPI 3.1 output support (#30) 

### Miscellaneous Tasks

- Bump version to 0.8.0 and update CHANGELOG 

### Testing

- Fix test naming and add missing module tests (#28) 
## [0.7.0] - 2026-01-22

### Bug Fixes

- Correct coverage measurement configuration (#19) 

### Documentation

- Add community files to repository root (#24) 

### Features

- Add Python 3.13 and 3.14 support (#29) 

### Miscellaneous Tasks

- Bump version to 0.7.0 and update CHANGELOG 
- Remove obsolete fix_tags.sh script (#22) 
- *(deps)* Update dev dependencies to latest versions (#26) 
- Add security scanning with Dependabot and CodeQL (#25) 
- Add pull request template (#23) 
- Add py.typed marker for PEP 561 compliance (#21) 
- Align pre-commit hooks with pyproject.toml settings (#20) 
- Add GitHub issue templates 
## [0.6.1] - 2026-01-22

### Documentation

- Update changelog 

### Other

- Bump version to 0.6.1 

### Refactor

- Adopt Python 3.10 type hint syntax (PEP 604/585) (#9) 
## [0.6.0] - 2026-01-21

### Documentation

- Update changelog 

### Miscellaneous Tasks

- Drop python 3.9 support 
- Fix mypy strict type checks 

### Other

- Bump version to 0.6.0 

### Styling

- Resolve lint issues 
- Format code with ruff and black 
## [0.5.1] - 2026-01-21

### Bug Fixes

- Normalize pydantic schemas into components 

### Documentation

- Update changelog 
- Enhance documentation with comprehensive guides 

### Other

- Bump version to 0.5.1 
## [0.5.0] - 2025-09-04

### Documentation

- Update changelog 
- Add comprehensive documentation and update configuration 
- Update changelog 

### Features

- Enhance OpenAPI generation with caching and error handling 
- Add server info, monitoring, and CLI tools 
- Enhance Swagger UI security and input validation 
- Add high-performance caching system 
- Add comprehensive error handling system 

### Miscellaneous Tasks

- *(docs)* Fix hatch run by removing nonexistent docs env 
- Fix version check path in release workflow 

### Other

- Bump version to 0.5.0 
## [0.4.1] - 2025-06-22

### Bug Fixes

- *(makefile)* Correct Python version check to support 3.9+ 

### Documentation

- Update development guide to reflect Hatch and Makefile integration 

### Miscellaneous Tasks

- Add GitHub Actions release workflow 
- *(docs)* Reuse Makefile install step in docs workflow 
- *(docs)* Rename deploy-docs.yml to docs.yml for clearer workflow separation 
- *(ci)* Replace test.yml with ci-test.yml for clarity and maintainability 
- *(build)* Clean up config and align with Hatch-based Makefile execution 
- Improve Makefile with Python 3.9+ check, .PHONY, and cross-platform venv support 

### Other

- Bump version to 0.4.1 
- *(pyproject)* Configure hatch build and publish targets 
- *(makefile)* Add Hatch-based automation for test, build, release 
## [0.4.0] - 2025-05-13

### Bug Fixes

- Move isort settings under lint section in pyproject.toml 
- *(example)* Resolve double /api prefix and update route in spec 
- *(openapi)* Avoid requestBody for GET methods 
- Add type hints and support Pydantic v2, clean test/lint output 

### Documentation

- Update full documentation and add OpenAPI preview 
- *(readme)* Remove collapsed quickstart section and refine examples 
- *(readme)* Fix unclosed code block after function example 
- *(readme)* Revise Quick Start example 
- Update development checklist in English and reflect current progress 
- Restructure documentation with updated README and index 
- Add placeholder markdown files to fix mkdocs build warnings 
- Restructure mkdocs.yml with full nav and example sections 
- *(readme)* Clarify that only Pydantic v2 is supported 
- *(decorator)* Expand example section with Hello World and Pydantic CRUD 
- Add comprehensive Usage Guide (docs/usage_guide.md) 
- Add file header comment to decorator.py 
- Add Quick Start section and refresh README badges 
- *(todo_api)* Add detailed docstrings for all endpoints and models 
- Add badges to README for PyPI, CI, Docs, and License 
- Add mkdocs.md with instructions for local preview and GitHub Pages deployment 
- Add detailed docstrings and usage examples to decorator and openapi modules 
- Enhance index.md with project overview and documentation links 
- Split development instructions into development.md 

### Features

- Add Swagger UI support and update example functions 
- Add Pydantic v1/v2 compatibility and schema utils 
- *(example)* Add complete CRUD implementation to todo_crud_api example 
- *(example)* Add todo_api with create and list endpoints 

### Miscellaneous Tasks

- Release v0.4.0 
- Release v0.4.0 
- Add junit.xml to .gitignore 
- Update pre-commit config to include black, ruff, mypy, and bandit 
- Add pre-commit run to check command in Makefile 
- Update imports and apply quality checks using ruff, black, mypy, and pytest 
- Update ruff settings for Python 3.9, improve import sorting, and adjust linting options 
- Upload coverage to Codecov only from Python 3.9 job 
- Add multi-version test support for Python 3.9–3.12 
- *(codecov)* Upload JUnit test results to Codecov for test insights 
- *(codecov)* Simplify upload step and rely on auto file detection 
- *(codecov)* Switch to tokenless upload so fork PRs report coverage 
- *(coverage)* Ensure relative paths in coverage.xml via .coveragerc 
- *(docs)* Pin MkDocs build workflow to Python 3.8 
- *(codecov)* Add codecov.yml with build_root and status thresholds 
- Fix Codecov upload path and add .coveragerc 
- Add Codecov upload step with v5 action 
- Run tests in dedicated venv to fix Makefile coverage path 
- *(mypy)* Exclude examples directory from type checking 
- *(pre-commit)* Configure mypy to use pyproject.toml 
- Update dependencies or project settings 
- Switch to make coverage in GitHub Actions workflow 
- Verify mkdocs build before deploy and add [docs] extra to pyproject.toml 
- Debug coverage.xml generation and allow 0% threshold 
- Fix import error by adding PYTHONPATH for examples 
- Add test workflow directory and GitHub Actions test.yml 
- Update pre-commit hook versions 

### Other

- Add coverage and coverage-html targets to Makefile 

### Refactor

- *(example)* Rename todo_api to todo_crud_api 
- *(openapi)* Remove hard-coded /api base path and servers entry 
- *(decorator)* Reorder parameters and registry keys for clarity 
- *(examples)* Replace obsolete openapi_json sample with hello_openapi and update tests 
- *(example)* Drop Pydantic dependency and polish Markdown description 
- *(example)* Apply typed openapi decorator to fix mypy issue 

### Styling

- *(readme)* Remove duplicate horizontal rules before Quick Start 

### Testing

- Align OpenAPI tests with /api prefix and enable pytest -v 
- Add pytest-cov and configure coverage report for Codecov 
## [0.3.0] - 2025-05-07

### Documentation

- Add full documentation with index, usage, contributing and mkdocs config 
- Update milestones.md with latest project roadmap 
- Update milestones.md with latest project roadmap 
- Update MILESTONES.md to reflect v0.2.0 completion and outline M3 goals 
- Generate changelog for v0.2.0 

### Features

- Add /openapi.yaml endpoint to return OpenAPI spec in YAML format 
- Support markdown in description and update related OpenAPI spec tests 
- Support operationId and tags in OpenAPI spec with tests 
- Implement automatic inference of route and method from function app metadata 
- Infer HTTP method and route path from decorator metadata 
- Support response schema and examples in OpenAPI output 
- Support OpenAPI parameters and requestBody in decorator and schema 

### Miscellaneous Tasks

- Release v0.3.0 
- Add mypy config to ignore missing imports for PyYAML 
- Ignore .github and .vscode directories 
- Fix PYTHONPATH for tests and add __init__.py files 
- Fix changelog generation to use local git-changelog binary 

### Testing

- Add OpenAPI spec test for cookie parameter support 
- Add test for OpenAPI schema generation using Pydantic models 
- Add tests/ directory for unit tests 
## [0.2.0] - 2025-05-03

### Documentation

- Update milestones for v0.2.0 
- Add development milestones checklist 

### Features

- Add OpenAPI decorator and spec generator with example function 

### Miscellaneous Tasks

- Release v0.2.0 
- Normalize line endings to LF using .editorconfig 
- Update ruff lint command to use 'check' subcommand 
- Add pre-commit configuration 
- *(pyproject)* Add git-changelog to dev dependencies 
- *(makefile)* Add versioning, changelog, and release automation commands 
- *(release)* Bump version to 0.1.1 
- *(build)* Remove static version to enable hatch versioning 
- Update Makefile with uv install and versioning commands 
- Set initial version in __init__.py 
- Add hatch-based versioning support 
<!-- generated by git-cliff -->
