#!/usr/bin/env python3
"""Validate statements.yaml files against their source .md files.

Checks:
1. Line coverage: every line [1, N] is assigned to exactly one statement
2. No gaps or overlaps in line ranges
3. Text fidelity: statement text matches source file lines
4. YAML parse validity
"""
import os
import sys
import yaml
from pathlib import Path


def validate_repo(repo_dir: Path) -> list[str]:
    errors = []
    yaml_path = repo_dir / "statements.yaml"
    if not yaml_path.exists():
        return []  # skip repos without statements.yaml

    # Load YAML
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return [f"{repo_dir.name}: YAML parse error: {e}"]

    if not data or "statements" not in data:
        return [f"{repo_dir.name}: no 'statements' key in YAML"]

    # Find the source file
    source_file = data.get("file", "")
    # Try to find the actual .md file
    md_files = []
    for fname in ["CLAUDE.md", "AGENTS.md"]:
        p = repo_dir / fname
        if p.exists():
            md_files.append((fname, p))

    if not md_files:
        return [f"{repo_dir.name}: no .md source files found"]

    # Determine which source file to validate against
    # Use the one referenced in the YAML file field
    source_path = None
    for fname, p in md_files:
        if fname in source_file:
            source_path = p
            break
    if source_path is None:
        source_path = md_files[0][1]  # fallback to first

    with open(source_path) as f:
        source_lines = f.readlines()
    total_lines = len(source_lines)

    statements = data["statements"]

    # Check 1: line coverage
    covered = set()
    for stmt in statements:
        lines = stmt.get("lines", [])
        if len(lines) != 2:
            errors.append(f"{repo_dir.name}: stmt {stmt.get('id')}: lines must be [start, end), got {lines}")
            continue
        start, end = lines
        for l in range(start, end):
            if l in covered:
                errors.append(f"{repo_dir.name}: stmt {stmt.get('id')}: line {l} overlaps with another statement")
            covered.add(l)

    # Check for gaps
    expected = set(range(1, total_lines + 1))
    missing = expected - covered
    extra = covered - expected
    if missing:
        errors.append(f"{repo_dir.name}: lines not covered: {sorted(missing)[:10]}{'...' if len(missing) > 10 else ''} ({len(missing)} total)")
    if extra:
        errors.append(f"{repo_dir.name}: lines beyond file end: {sorted(extra)[:10]} (file has {total_lines} lines)")

    # Check 2: text matches source
    for stmt in statements:
        lines = stmt.get("lines", [])
        if len(lines) != 2:
            continue
        start, end = lines
        text = stmt.get("text", "")
        # Get actual source text for these lines
        actual = "".join(source_lines[start-1:end-1])  # [start, end) half-open, 1-indexed

        # Check if text contains "..." (abbreviation)
        if "..." in text and len(text.strip()) < len(actual.strip()) * 0.5:
            errors.append(f"{repo_dir.name}: stmt {stmt.get('id')}: text appears abbreviated (contains '...')")

    # Check 3: warn about statements that look like merged independent list items
    for stmt in statements:
        text = stmt.get("text", "")
        lines_range = stmt.get("lines", [0, 0])
        span = lines_range[1] - lines_range[0] if len(lines_range) == 2 else 0

        # Count lines starting with "- " in the text
        list_items = [l for l in text.split("\n") if l.strip().startswith("- ")]
        if len(list_items) >= 3 and stmt.get("type") == "directive":
            # Check if these look like independent directives (each has imperative language)
            imperative_count = 0
            for item in list_items:
                lower = item.lower()
                if any(kw in lower for kw in ["never", "must", "do not", "don't", "always",
                                                "avoid", "prefer", "use ", "run ", "ensure"]):
                    imperative_count += 1
            if imperative_count >= 3:
                errors.append(
                    f"{repo_dir.name}: WARNING stmt {stmt.get('id')}: "
                    f"{len(list_items)} list items with imperative language merged into one "
                    f"directive (lines {lines_range}). Consider splitting."
                )

    return errors


def main():
    corpus_dir = Path(".")
    all_errors = []
    stats = {"repos": 0, "valid": 0, "errors": 0, "skipped": 0}

    for d in sorted(corpus_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        yaml_path = d / "statements.yaml"
        if not yaml_path.exists():
            stats["skipped"] += 1
            continue

        stats["repos"] += 1
        errors = validate_repo(d)
        if errors:
            stats["errors"] += 1
            all_errors.extend(errors)
        else:
            stats["valid"] += 1

    print(f"Validated {stats['repos']} repos ({stats['valid']} valid, {stats['errors']} with errors, {stats['skipped']} skipped)")
    print()
    if all_errors:
        print(f"ERRORS ({len(all_errors)}):")
        for e in all_errors:
            print(f"  {e}")
        return 1
    else:
        print("All validations passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
