"""Export the project's existing FastAPI/Jinja UI for GitHub Pages.

The generated pages preserve the original project templates and static assets.
Server-side inference APIs remain part of the FastAPI application and are not
implemented by GitHub Pages.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "patho_cot_web"
TEMPLATES = WEB / "templates"
DOCS = ROOT / "docs"
BASE_PATH = "/patho-cot/"


def prefix_absolute_urls(html: str) -> str:
    """Move root-relative browser URLs under the GitHub Pages project path."""
    return re.sub(r"([\"'])/(?!/|patho-cot/)", rf"\1{BASE_PATH}", html)


def write_page(relative_dir: str, html: str) -> None:
    output_dir = DOCS / relative_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(
        prefix_absolute_urls(html), encoding="utf-8", newline="\n"
    )


def copy_static() -> None:
    destination = DOCS / "static"
    shutil.copytree(
        WEB / "static",
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("uploads", "results", "__pycache__"),
    )
    for runtime_dir in (destination / "uploads", destination / "results"):
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / ".gitkeep").write_text("", encoding="utf-8")


def main() -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(("html", "xml")),
    )

    pages: list[tuple[str, str, dict]] = [
        ("", "landing.html", {}),
        ("dashboard", "dashboard.html", {}),
        ("multi", "multi.html", {}),
        ("history", "history.html", {"records": []}),
        ("datasets", "datasets.html", {}),
        ("models", "models.html", {}),
        ("report", "report.html", {}),
        ("explorer", "explorer.html", {}),
        ("m", "m.html", {}),
        (
            "history/detail",
            "history_detail.html",
            {"record": None, "steps": {}, "events": [], "multi_summary": None},
        ),
    ]
    pages.extend(
        (f"diagnose/{step}", f"diagnose_{step}_{name}.html", {"step": step, "total_steps": 6})
        for step, name in (
            (1, "quality"),
            (2, "organ"),
            (3, "detection"),
            (4, "nature"),
            (5, "subtype"),
            (6, "report"),
        )
    )

    for output_dir, template_name, context in pages:
        rendered = env.get_template(template_name).render(**context)
        write_page(output_dir, rendered)

    copy_static()
    print(f"Exported {len(pages)} original project pages to {DOCS}")


if __name__ == "__main__":
    main()

