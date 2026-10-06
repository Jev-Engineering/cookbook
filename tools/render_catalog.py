"""Render the generated regions of README.md from catalog/recipes.json.

A recipe counts as published once recipes/<slug>/notebook.ipynb exists; until
then it is listed as coming soon. Standard library only.

    python tools/render_catalog.py           # rewrite README.md in place
    python tools/render_catalog.py --check   # exit 1 if README.md is stale
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/Jev-Engineering/cookbook"
PINK, INK, MAGENTA = "F386A1", "1E1E1E", "E551BA"


def badge(label: str, message: str, color: str) -> str:
    def esc(text: str) -> str:
        return text.replace("-", "--").replace("_", "__").replace(" ", "%20")

    url = f"https://img.shields.io/badge/{esc(label)}-{esc(message)}-{color}?style=flat-square&labelColor={INK}"
    return f"![{label}: {message}]({url})"


def is_published(recipe: dict) -> bool:
    return (ROOT / "recipes" / recipe["slug"] / "notebook.ipynb").is_file()


def status_cell(recipe: dict) -> str:
    if is_published(recipe):
        return f"[Open notebook](recipes/{recipe['slug']}/notebook.ipynb)"
    issue = recipe.get("issue")
    return f"Coming soon · [#{issue}]({REPO_URL}/issues/{issue})" if issue else "Coming soon"


def decision_cell(recipe: dict) -> str:
    return " + ".join(f"`{t}`" for t in recipe["decision_types"])


def render_progress(catalog: dict) -> str:
    recipes = catalog["recipes"]
    done = sum(is_published(r) for r in recipes)
    status = "coming soon" if done == 0 else ("in progress" if done < len(recipes) else "complete")
    badges = [
        badge("Recipes", f"{done} of {len(recipes)} published", PINK),
        badge("Status", status, MAGENTA),
        badge("Categories", str(len({r["category"] for r in recipes})), PINK),
        badge("Levels", str(len(catalog["levels"])), PINK),
    ]
    return " ".join(badges)


def render_levels(catalog: dict) -> str:
    lines = [
        "| Level | Name | What a notebook at this level involves | Recipes |",
        "| :---: | --- | --- | :---: |",
    ]
    for level in catalog["levels"]:
        ranks = [r["rank"] for r in catalog["recipes"] if r["level"] == level["level"]]
        anchor = f"#level-{level['level']}--{level['name'].lower()}"
        lines.append(
            f"| **{level['level']}** | [{level['name']}]({anchor}) | {level['scope']} | "
            f"{len(ranks)}<br><sub>{ranks[0]:02d} to {ranks[-1]:02d}</sub> |"
        )
    return "\n".join(lines)


def render_categories(catalog: dict) -> str:
    groups: dict[str, list[dict]] = {}
    for recipe in catalog["recipes"]:
        groups.setdefault(recipe["category"], []).append(recipe)
    lines = ["| Category | Recipes | Levels | Recipe numbers |", "| --- | :---: | :---: | --- |"]
    for name, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        levels = sorted({r["level"] for r in items})
        span = str(levels[0]) if len(levels) == 1 else f"{levels[0]} to {levels[-1]}"
        numbers = " ".join(f"`{r['rank']:02d}`" for r in items)
        lines.append(f"| **{name}** | {len(items)} | {span} | {numbers} |")
    return "\n".join(lines)


def render_recipes(catalog: dict) -> str:
    blocks = []
    for level in catalog["levels"]:
        items = [r for r in catalog["recipes"] if r["level"] == level["level"]]
        lines = [
            f"### Level {level['level']} · {level['name']}",
            "",
            f"{level['scope']}",
            "",
            "| # | Recipe | Category | Decision | Status |",
            "| :---: | --- | --- | --- | --- |",
        ]
        for r in items:
            lines.append(
                f"| {r['rank']:02d} | **{r['title']}**<br>{r['use_case']} | {r['category']} | "
                f"{decision_cell(r)} | {status_cell(r)} |"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_sources(catalog: dict) -> str:
    lines = ["| ID | Reference | What it supports |", "| :---: | --- | --- |"]
    for s in catalog["sources"]:
        lines.append(f"| {s['id']} | [{s['reference']}]({s['url']}) | {s['supports']} |")
    return "\n".join(lines)


REGIONS = {
    "progress": render_progress,
    "levels": render_levels,
    "categories": render_categories,
    "recipes": render_recipes,
    "sources": render_sources,
}


def render(readme: str, catalog: dict) -> str:
    for name, fn in REGIONS.items():
        pattern = re.compile(
            rf"(<!-- catalog:{name}:start -->\n)(?:.*?\n)?(<!-- catalog:{name}:end -->)", re.S
        )
        if not pattern.search(readme):
            raise SystemExit(f"README.md is missing the catalog:{name} markers")
        readme = pattern.sub(lambda m, fn=fn: m.group(1) + fn(catalog) + "\n" + m.group(2), readme)
    return readme


def main() -> int:
    catalog = json.loads((ROOT / "catalog" / "recipes.json").read_text(encoding="utf-8"))
    path = ROOT / "README.md"
    current = path.read_text(encoding="utf-8")
    updated = render(current, catalog)
    if "--check" in sys.argv[1:]:
        if updated != current:
            print("README.md is out of date. Run: python tools/render_catalog.py")
            return 1
        return 0
    if updated != current:
        path.write_text(updated, encoding="utf-8", newline="\n")
        print("README.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
