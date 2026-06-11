# Project Dependency Status & EOL Tracking

This file tracks the third-party libraries used across this project, their current requirements, latest stable versions, End-of-Life (EOL) status, and recommended update actions.

> [!NOTE]
> This file is maintained automatically and manually via the agentic framework. 
> To update version numbers and analyze deprecations, run the check script:
> ```bash
> python3 check_dependencies.py
> ```

## Dependency Audit Table

| Dependency | Current Version | Latest Version | EOL / Deprecation Status | Action Required (Yes/No) | Last Audited | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `beautifulsoup4` | `>=4.12.0` | `4.15.0` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `cairosvg` | `>=2.7.0` | `2.9.0` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `curl-cffi` | `>=0.7.0` | `0.15.0` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `ebooklib` | `>=0.18` | `0.20` | 🔴 Legacy (Mammoth/Markdownify preferred) | **Yes** | 2026-06-11 | - |
| `edge-tts` | `>=7.2.8` | `7.2.8` | 🟢 Active | No | 2026-06-11 | - |
| `flask` | `>=3.0.0` | `3.1.3` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `google-antigravity` | `Any` | `0.1.2` | 🟢 Active (Core SDK) | No | 2026-06-11 | - |
| `google-cloud-pubsub` | `>=2.19.0` | `2.39.0` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `google-genai` | `>=1.0.0` | `2.8.0` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `mammoth` | `>=1.6.0` | `1.12.0` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `markdownify` | `>=0.11.6` | `1.2.2` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `nbconvert` | `>=7.0.0` | `7.17.1` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `numpy` | `>=1.20.0` | `2.4.6` | ⚠️ NumPy 1.x EOL expected late 2026; NumPy 2.x is active. | **Yes** | 2026-06-11 | - |
| `openpyxl` | `>=3.1.0` | `3.1.5` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `pillow` | `>=9.0.0` | `12.2.0` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `playwright` | `>=1.60.0` | `1.60.0` | 🟢 Active | No | 2026-06-11 | - |
| `pymupdf` | `>=1.23.0` | `1.27.2.3` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `python-dotenv` | `>=1.0.0` | `1.2.2` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `python-pptx` | `>=0.6.21` | `1.0.2` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `reportlab` | `>=4.0.0` | `4.5.1` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `requests` | `>=2.31.0` | `2.34.2` | 🟢 Active | **Yes** | 2026-06-11 | - |
| `svglib` | `>=1.5.0` | `1.6.0` | 🔴 Legacy (Unmaintained, CairoSVG preferred) | **Yes** | 2026-06-11 | - |

## Agentic Audit Guidelines

When an AI agent is asked to review or update dependencies:
1. **Execute the Script**: Run `python3 check_dependencies.py` to refresh all PyPI version listings.
2. **Search EOL Statuses**: For packages marked with EOL warnings or major version differences, use Google Search to verify deprecation timelines and compatibility risks (e.g. NumPy 2.0 migration boundaries).
3. **Recommend Actions**: Update the **Action Required** column to `Yes` or `No` and document the rationale in the **Notes** column.
4. **Update Requirements**: If an update action is approved, edit the corresponding `requirements.txt` file and verify compatibility in WSL.
