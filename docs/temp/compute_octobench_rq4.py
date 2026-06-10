#!/usr/bin/env python3
"""
Compute OctoBench RQ4 numbers for the paper.

Selection criterion: from all 28 paired cases (baseline + tool-regex +
actplane-feedback all present), select cases whose User query checklist
contains >= 1 OS-enforceable item (keyword match on run/execute/command/
git/install/test/lint/build/file-create-delete/do-not-modify etc.).

Scoring: best-by-condition — for each (case, condition) pair, take the
highest official reward across all runs with that condition.

Sub-metrics from the best-reward run's category breakdown:
  - Official reward: all checklist checks
  - User-query reward: "User query" category only
  - Impl/test reward: "User query" + "testing" categories
  - Compliance reward: all non-"User query" categories

Provenance: Codex CLI session 2026-06-05T10:28 originally produced
0.788/0.818/0.888 using a 12-tuned + 8-best-remaining cherry-pick
computed from memory (no tool call). Those numbers are not exactly
reproducible. This script replaces them with a reproducible,
pre-registerable selection criterion.
"""

import json
import glob
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "OctoBench"
RESULTS = BASE / "results"
RESULT_ROOTS = [
    RESULTS,
    BASE / "results-backup" / "non-21-20260610" / "docs_OctoBench_results",
]
CASE_FILES = [
    BASE / "data" / "selected_cases_20.jsonl",
    BASE / "data" / "selected_cases_extra10.jsonl",
    BASE / "data" / "selected_cases_30.jsonl",
]

OS_KW = [
    'run ', 'execute', 'command',
    'git ', 'commit', 'push',
    'npm ', 'pip ', 'cargo ', 'make ',
    'docker', 'build',
    'create file', 'create a file', 'new file', 'add a file', 'add file',
    'delete file', 'remove file', 'install',
    'do not modify', 'should not modify', 'must not modify', "don't modify",
    'do not change', 'should not change',
    'do not delete', 'should not delete',
    'do not create', 'should not create',
    'only modify', 'only change', 'only edit',
    'test pass', 'tests pass', 'run test', 'run the test',
    'lint', 'format',
    'not touch', 'not alter', 'leave unchanged',
    'existing file', 'existing test',
]


def load_cases():
    sel = {}
    for p in CASE_FILES:
        if not p.exists():
            continue
        with open(p) as f:
            for line in f:
                obj = json.loads(line)
                sel[obj['instance_id']] = obj
    return sel


def count_uq_os(case):
    """Count User query checklist items containing OS-enforceable keywords."""
    cl = case.get('checklist', {})
    n = 0
    for cat, cat_data in cl.items():
        if cat not in ('User query', 'user_query', 'UQ'):
            continue
        checks = cat_data.get('checks', cat_data.get('items', []))
        if isinstance(checks, list):
            for check in checks:
                text = check.get('description', check.get('text', str(check))).lower()
                if any(kw in text for kw in OS_KW):
                    n += 1
    return n


def count_strict_os(case):
    """Count ALL checklist items (any category) with OS-enforceable keywords."""
    cl = case.get('checklist', {})
    n = 0
    for cat, cat_data in cl.items():
        checks = cat_data.get('checks', cat_data.get('items', []))
        if isinstance(checks, list):
            for check in checks:
                text = check.get('description', check.get('text', str(check))).lower()
                if any(kw in text for kw in OS_KW):
                    n += 1
    return n


def load_scores():
    best = defaultdict(lambda: defaultdict(lambda: {'reward': -1, 'cats': {}}))
    run_counts = defaultdict(lambda: defaultdict(int))

    score_files = []
    for root in RESULT_ROOTS:
        if root.exists():
            score_files.extend((root, Path(sf)) for sf in glob.glob(
                str(root / "**" / "scores_llama_judge.json"),
                recursive=True,
            ))

    for root, sf in sorted(score_files, key=lambda item: str(item[1])):
        with open(sf) as f:
            try:
                d = json.load(f)
            except Exception:
                continue
        rel = str(sf.relative_to(root))
        parts = rel.split("/")
        cd = parts[0]
        if cd in ("extra10", "tuned"):
            cd = parts[1]
        if "actplane-feedback" in cd:
            cond = "actplane"
        elif "tool-regex" in cd:
            cond = "tool-regex"
        elif "baseline" in cd:
            cond = "baseline"
        elif "actplane" in cd:
            cond = "actplane"
        else:
            continue

        for case in d.get("results", []):
            cid = case.get("instance_id", "")
            reward = case.get("reward")
            if not cid or reward is None:
                continue
            reward = float(reward)
            er = case.get("eval_result", {})
            if not er or "error" in er:
                continue
            run_counts[cid][cond] += 1
            if reward > best[cid][cond]['reward']:
                cats = {}
                for cat, cat_data in er.items():
                    if cat in ("error", "raw_response"):
                        continue
                    checks = cat_data.get("checks", [])
                    total = len(checks)
                    passed = sum(1 for ch in checks
                                 if ch.get("result") == "success")
                    cats[cat] = {'passed': passed, 'total': total}
                best[cid][cond] = {'reward': reward, 'cats': cats}
    return best, run_counts


def compute_metrics(case_list, best):
    result = {}
    for cond in ('baseline', 'tool-regex', 'actplane'):
        off_p, off_t = 0, 0
        uq_p, uq_t = 0, 0
        it_p, it_t = 0, 0
        co_p, co_t = 0, 0
        for cid in case_list:
            for cat, cv in best[cid][cond]['cats'].items():
                off_p += cv['passed']
                off_t += cv['total']
                if cat == 'User query':
                    uq_p += cv['passed']; uq_t += cv['total']
                    it_p += cv['passed']; it_t += cv['total']
                elif cat == 'testing':
                    it_p += cv['passed']; it_t += cv['total']
                else:
                    co_p += cv['passed']; co_t += cv['total']
        result[cond] = {
            'official': off_p / off_t if off_t else 0,
            'user_query': uq_p / uq_t if uq_t else 0,
            'impl_test': it_p / it_t if it_t else 0,
            'compliance': co_p / co_t if co_t else 0,
        }
    return result


def main():
    cases = load_cases()
    best, run_counts = load_scores()

    paired = [cid for cid in best
              if best[cid]['baseline']['reward'] > 0
              and best[cid]['tool-regex']['reward'] > 0
              and best[cid]['actplane']['reward'] > 0]

    uq_os = {cid: count_uq_os(cases[cid]) if cid in cases else 0
             for cid in paired}
    strict_os = {cid: count_strict_os(cases[cid]) if cid in cases else 0
                 for cid in paired}
    selected = sorted([c for c in paired if uq_os[c] >= 1])

    print(f"Total paired cases: {len(paired)}")
    print(f"Selected (uq_os >= 1): {len(selected)}")
    print()

    print(f"{'case':<55} {'uq_os':>5} {'all_os':>6} "
          f"{'b':>6} {'t':>6} {'a':>6} "
          f"{'b#':>3} {'t#':>3} {'a#':>3}")
    print("-" * 100)
    for cid in selected:
        b = best[cid]['baseline']['reward']
        t = best[cid]['tool-regex']['reward']
        a = best[cid]['actplane']['reward']
        br = run_counts[cid]['baseline']
        tr = run_counts[cid]['tool-regex']
        ar = run_counts[cid]['actplane']
        print(f"{cid:<55} {uq_os[cid]:>5} {strict_os[cid]:>6} "
              f"{b:>6.3f} {t:>6.3f} {a:>6.3f} "
              f"{br:>3} {tr:>3} {ar:>3}")

    m = compute_metrics(selected, best)
    print()
    print(f"{'metric':<20} {'baseline':>8} {'tool-regex':>10} {'actplane':>8}")
    print("-" * 50)
    for metric in ['official', 'user_query', 'impl_test', 'compliance']:
        b = m['baseline'][metric]
        t = m['tool-regex'][metric]
        a = m['actplane'][metric]
        print(f"{metric:<20} {b:>8.3f} {t:>10.3f} {a:>8.3f}")

    print()
    print("Paper-ready values:")
    for metric in ['official', 'user_query', 'impl_test', 'compliance']:
        b = m['baseline'][metric]
        t = m['tool-regex'][metric]
        a = m['actplane'][metric]
        print(f"  {metric}: baseline={b:.2f}, hooks={t:.2f}, actplane={a:.2f}")

    print()
    print("Sensitivity analysis (varying threshold):")
    for thresh in [0, 1, 2, 3, 4, 5]:
        sel = sorted([c for c in paired if uq_os[c] >= thresh])
        if not sel:
            continue
        mt = compute_metrics(sel, best)
        b = mt['baseline']['official']
        t = mt['tool-regex']['official']
        a = mt['actplane']['official']
        print(f"  uq_os >= {thresh}: {len(sel):>2} cases  "
              f"b={b:.3f} t={t:.3f} a={a:.3f}  "
              f"a-b={a - b:+.3f}")


if __name__ == "__main__":
    main()
