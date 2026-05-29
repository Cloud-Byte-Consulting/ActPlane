#!/usr/bin/env python3
"""Generate all RQ figures (6 separate PNGs).

Usage: cd docs/corpus && python3 ../tmp/fig_all_rqs.py
Output: docs/tmp/fig{1..6}_*.png
"""
import yaml, os, collections
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

COLLAPSE = {
    'Debugging': 'Development Process', 'Project Management': 'Development Process',
    'Performance': 'Implementation Details', 'UI/UX': 'Implementation Details',
}
TOPIC_ORDER = [
    'Development Process', 'Implementation Details', 'Architecture',
    'Build and Run', 'AI Integration', 'Testing',
    'System Overview', 'Documentation', 'Configuration & Environment',
    'Security', 'DevOps', 'Maintenance',
]
SHORT = {
    'Configuration & Environment': 'Config & Env',
    'Implementation Details': 'Impl. Details',
    'Development Process': 'Dev. Process',
}

desc_by = collections.Counter()
dir_by = collections.Counter()
lines_by = collections.Counter()
repo_stats = []

for d in sorted(os.listdir('.')):
    yf = os.path.join(d, 'statements.yaml')
    if not os.path.isfile(yf): continue
    with open(yf) as f:
        data = yaml.safe_load(f)
    if not data or 'statements' not in data: continue
    stmts = data['statements']
    r_desc = r_dir = 0
    for s in stmts:
        topic = COLLAPSE.get(s.get('topic', ''), s.get('topic', ''))
        span = s['lines'][1] - s['lines'][0] if len(s.get('lines', [])) == 2 else 0
        if s.get('type') == 'description':
            desc_by[topic] += 1; r_desc += 1
        else:
            dir_by[topic] += 1; r_dir += 1
        lines_by[topic] += span
    repo_stats.append({'repo': d.replace('__', '/'), 'desc': r_desc, 'dir': r_dir,
                       'total': len(stmts), 'dir_pct': 100 * r_dir / len(stmts) if stmts else 0})

topics = TOPIC_ORDER
labels = [SHORT.get(t, t) for t in topics]
desc = np.array([desc_by[t] for t in topics])
dire = np.array([dir_by[t] for t in topics])
lines_arr = np.array([lines_by[t] for t in topics])
total = desc + dire
outdir = os.path.join(os.path.dirname(os.path.abspath('.')), 'tmp')

# ===== Fig 1: RQ1 - Per-repo directive fraction =====
fig, ax = plt.subplots(figsize=(8, 5))
dir_pcts = sorted([r['dir_pct'] for r in repo_stats])
colors = ['#FF6B6B' if p >= 50 else '#4ECDC4' for p in dir_pcts]
ax.bar(range(len(dir_pcts)), dir_pcts, color=colors, width=1.0, edgecolor='none')
ax.axhline(y=np.median(dir_pcts), color='black', linestyle='--', linewidth=1.5,
           label=f'Median = {np.median(dir_pcts):.1f}%')
ax.axhline(y=50, color='gray', linestyle=':', linewidth=1, alpha=0.5)
p_dir = mpatches.Patch(color='#FF6B6B', label='Majority directive (>50%)')
p_desc = mpatches.Patch(color='#4ECDC4', label='Majority description (<50%)')
ax.legend(handles=[p_dir, p_desc, ax.get_lines()[0]], fontsize=9, loc='upper left')
ax.set_xlabel('Repositories (sorted by directive fraction)', fontsize=11)
ax.set_ylabel('Directive Fraction (%)', fontsize=11)
ax.set_title('RQ1: What fraction of instruction-file content is directive?', fontsize=12, fontweight='bold')
ax.set_ylim(0, 105)
ax.text(len(dir_pcts) * 0.55, 8,
        f'n = {len(dir_pcts)} repos\n{sum(dire)}/{sum(total)} stmts = {100 * sum(dire) / sum(total):.1f}% directive',
        fontsize=9, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig1_rq1_directive_fraction.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 1')

# ===== Fig 2: RQ2a - Topic prevalence =====
fig, ax = plt.subplots(figsize=(8, 5))
y = np.arange(len(topics))
ax.barh(y, total[::-1], color='#6C5CE7', edgecolor='white', linewidth=0.5, label='Statements')
for i, v in enumerate(total[::-1]):
    ax.text(v + 5, i, f'{v} ({100 * v / sum(total):.1f}%)', va='center', fontsize=8)
ax.set_yticks(y); ax.set_yticklabels(labels[::-1], fontsize=10)
ax.set_xlabel('Statement Count', fontsize=11)
ax.set_title('RQ2a: Which topics dominate instruction files?', fontsize=12, fontweight='bold')
ax.legend(fontsize=9)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig2_rq2a_topic_prevalence.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 2')

# ===== Fig 3: RQ2b - Directive ratio by topic =====
fig, ax = plt.subplots(figsize=(8, 5))
dir_ratio = np.array([100 * d / t if t > 0 else 0 for d, t in zip(dire, total)])
si = np.argsort(dir_ratio)
sr = dir_ratio[si]; sl = [labels[i] for i in si]
colors3 = ['#FF6B6B' if p > 70 else '#FFD93D' if p > 40 else '#4ECDC4' for p in sr]
ax.barh(y, sr, color=colors3, edgecolor='white', linewidth=0.5)
avg_line = ax.axvline(x=100 * sum(dire) / sum(total), color='black', linestyle='--', linewidth=1.5)
for i, (v, t) in enumerate(zip(sr, [total[j] for j in si])):
    ax.text(v + 1, i, f'{v:.0f}% (n={t})', va='center', fontsize=8)
p_high = mpatches.Patch(color='#FF6B6B', label='Directive-dominant (>70%)')
p_mid = mpatches.Patch(color='#FFD93D', label='Mixed (40-70%)')
p_low = mpatches.Patch(color='#4ECDC4', label='Description-dominant (<40%)')
ax.legend(handles=[p_high, p_mid, p_low, avg_line], labels=[
    'Directive-dominant (>70%)', 'Mixed (40-70%)', 'Description-dominant (<40%)',
    f'Overall avg ({100 * sum(dire) / sum(total):.1f}%)'], fontsize=8, loc='lower right')
ax.set_yticks(y); ax.set_yticklabels(sl, fontsize=10)
ax.set_xlabel('Directive Ratio (%)', fontsize=11)
ax.set_title('RQ2b: How does the directive ratio vary across topics?', fontsize=12, fontweight='bold')
ax.set_xlim(0, 105)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig3_rq2b_directive_ratio.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 3')

# ===== Fig 4: RQ2c - Statement-level vs file-level =====
chat_file_pct = {
    'Build and Run': 77.1, 'Implementation Details': 71.9, 'Architecture': 64.8,
    'Testing': 55.0, 'Development Process': 50.0, 'AI Integration': 40.0,
    'System Overview': 35.0, 'Documentation': 30.0, 'Configuration & Environment': 25.0,
    'Security': 14.5, 'DevOps': 10.0, 'Maintenance': 8.0,
}
fig, ax = plt.subplots(figsize=(8, 5))
stmt_pct = 100 * total / total.sum()
file_pct = np.array([chat_file_pct.get(t, 0) for t in topics])
w = 0.35
ax.barh(y + w / 2, stmt_pct[::-1], w, label='This study (% of statements)', color='#FF6B6B', alpha=0.85)
ax.barh(y - w / 2, file_pct[::-1], w, label='Chatlatanagulchai et al. (% of files)', color='#4ECDC4', alpha=0.85)
ax.set_yticks(y); ax.set_yticklabels(labels[::-1], fontsize=10)
ax.set_xlabel('Percentage (%)', fontsize=11)
ax.set_title('RQ2c: Does analysis granularity change topic ranking?', fontsize=12, fontweight='bold')
ax.legend(fontsize=9)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig4_rq2c_granularity_comparison.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 4')

# ===== Fig 5: RQ2d - Statement share vs line share =====
fig, ax = plt.subplots(figsize=(8, 5))
stmt_share = 100 * total / total.sum()
line_share = 100 * lines_arr / lines_arr.sum()
diff = stmt_share - line_share
s5 = np.argsort(diff); sd = diff[s5]; sl5 = [labels[i] for i in s5]
colors5 = ['#FF6B6B' if d > 0 else '#4ECDC4' for d in sd]
ax.barh(np.arange(len(sd)), sd, color=colors5, edgecolor='white')
ax.axvline(x=0, color='black', linewidth=1)
for i, (v, ss, ll) in enumerate(zip(sd, [stmt_share[j] for j in s5], [line_share[j] for j in s5])):
    side = 'left' if v < 0 else 'right'
    ax.text(v + (0.3 if v >= 0 else -0.3), i,
            f'{ss:.1f}% stmts / {ll:.1f}% lines', va='center', ha=side, fontsize=7.5)
p_terse = mpatches.Patch(color='#FF6B6B', label='Terse (more stmts per line)')
p_verbose = mpatches.Patch(color='#4ECDC4', label='Verbose (fewer stmts per line)')
ax.legend(handles=[p_terse, p_verbose], fontsize=9, loc='lower right')
ax.set_yticks(np.arange(len(sd))); ax.set_yticklabels(sl5, fontsize=10)
ax.set_xlabel('Statement share minus line share (percentage points)', fontsize=10)
ax.set_title('RQ2d: Which topics consist of terse directives vs. verbose descriptions?', fontsize=11, fontweight='bold')
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig5_rq2d_stmt_vs_line.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 5')

# ===== Fig 6: RQ3 - Directives per repo =====
fig, ax = plt.subplots(figsize=(8, 5))
repo_stats.sort(key=lambda r: r['dir'], reverse=True)
dc = [r['dir'] for r in repo_stats]
ax.bar(range(15), dc[:15], color='#FF6B6B', edgecolor='white', label='Top 15 repos')
ax.bar(range(15, len(dc)), dc[15:], color='#CCCCCC', edgecolor='white', label='Remaining repos')
ax.axhline(y=np.median(dc), color='black', linestyle='--', linewidth=1.5,
           label=f'Median = {np.median(dc):.0f}')
top10 = sum(dc[:10]) / sum(dc) * 100
ax.text(len(dc) * 0.5, max(dc) * 0.85,
        f'Top 10 repos = {top10:.1f}% of all directives\nMedian = {np.median(dc):.0f}, Max = {max(dc)}',
        fontsize=9, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
ax.set_xlabel('Repositories (sorted by directive count)', fontsize=11)
ax.set_ylabel('Number of Directives', fontsize=11)
ax.set_title('RQ3: How are directives distributed across repositories?', fontsize=12, fontweight='bold')
ax.legend(fontsize=9)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig6_rq3_directive_density.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 6')

# ===== RQ4 figures: Enforcement-level analysis =====

# Collect enforcement data
ENF_LEVELS = ['semantic_only', 'content', 'per_event', 'cross_event']
ENF_LABELS = ['Semantic-only', 'Content', 'Per-event', 'Cross-event']
ENF_COLORS = ['#95A5A6', '#3498DB', '#2ECC71', '#E74C3C']

enf_by_topic = {t: collections.Counter() for t in topics}
enf_total = collections.Counter()
repo_enf = []

for d in sorted(os.listdir('.')):
    yf = os.path.join(d, 'statements.yaml')
    if not os.path.isfile(yf): continue
    with open(yf) as f:
        data = yaml.safe_load(f)
    if not data or 'statements' not in data: continue
    r_enf = collections.Counter()
    for s in data['statements']:
        if s.get('type') != 'directive': continue
        e = s.get('enforceability')
        if e not in ENF_LEVELS: continue
        topic = COLLAPSE.get(s.get('topic', ''), s.get('topic', ''))
        enf_by_topic[topic][e] += 1
        enf_total[e] += 1
        r_enf[e] += 1
    r_dir_total = sum(r_enf.values())
    repo_enf.append({'repo': d.replace('__', '/'), 'total': r_dir_total, **{e: r_enf[e] for e in ENF_LEVELS}})

total_dir = sum(enf_total.values())

# ===== Fig 7: RQ4a - Overall enforceability =====
fig, ax = plt.subplots(figsize=(6, 4))
counts = [enf_total[e] for e in ENF_LEVELS]
pcts = [100 * c / total_dir for c in counts]
bars = ax.barh(ENF_LABELS[::-1], counts[::-1], color=ENF_COLORS[::-1], edgecolor='white')
for bar, c, p in zip(bars, counts[::-1], pcts[::-1]):
    ax.text(bar.get_width() + 10, bar.get_y() + bar.get_height() / 2,
            f'{c} ({p:.1f}%)', va='center', fontsize=9)
behavior_total = sum(counts[1:])
ax.set_xlabel('Count', fontsize=11)
ax.set_title('RQ4a: Enforcement level distribution', fontsize=12, fontweight='bold')
ax.text(0.95, 0.05, f'System-enforceable: {behavior_total} ({100 * behavior_total / total_dir:.1f}%)',
        transform=ax.transAxes, ha='right', fontsize=9,
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig7_rq4a_enforceability_overall.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 7')

# ===== Fig 8: RQ4b - Topic x enforceability (absolute) =====
fig, ax = plt.subplots(figsize=(10, 5))
y8 = np.arange(len(topics))
left = np.zeros(len(topics))
for ei, e in enumerate(ENF_LEVELS):
    vals = np.array([enf_by_topic[t][e] for t in topics])
    ax.barh(y8, vals[::-1], left=left, color=ENF_COLORS[ei], label=ENF_LABELS[ei], edgecolor='white', linewidth=0.5)
    left += vals[::-1]
ax.set_yticks(y8); ax.set_yticklabels(labels[::-1], fontsize=10)
ax.set_xlabel('Directive Count', fontsize=11)
ax.set_title('RQ4b: Enforcement level by topic (absolute)', fontsize=12, fontweight='bold')
ax.legend(fontsize=9, loc='lower right')
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig8_rq4b_topic_enforceability.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 8')

# ===== Fig 9: RQ4c - Topic x enforceability (normalized) =====
fig, ax = plt.subplots(figsize=(10, 5))
left9 = np.zeros(len(topics))
for ei, e in enumerate(ENF_LEVELS):
    vals = np.array([enf_by_topic[t][e] for t in topics])
    totals_topic = np.array([sum(enf_by_topic[t].values()) for t in topics])
    pct_vals = np.where(totals_topic > 0, 100 * vals / totals_topic, 0)
    ax.barh(y8, pct_vals[::-1], left=left9, color=ENF_COLORS[ei], label=ENF_LABELS[ei], edgecolor='white', linewidth=0.5)
    left9 += pct_vals[::-1]
ax.set_yticks(y8); ax.set_yticklabels(labels[::-1], fontsize=10)
ax.set_xlabel('Percentage (%)', fontsize=11)
ax.set_xlim(0, 105)
ax.set_title('RQ4c: Enforcement profile by topic (normalized)', fontsize=12, fontweight='bold')
ax.legend(fontsize=9, loc='lower right')
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig9_rq4c_topic_enforceability_pct.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 9')

# ===== Fig 10: RQ4d - Cumulative coverage =====
fig, ax = plt.subplots(figsize=(6, 4))
cum = [0]
for e in ENF_LEVELS:
    cum.append(cum[-1] + enf_total[e])
cum_pct = [100 * c / total_dir for c in cum]
x10 = ['None'] + ENF_LABELS
ax.plot(x10, cum_pct, 'o-', color='#E74C3C', linewidth=2, markersize=8)
for i, (xl, yv) in enumerate(zip(x10, cum_pct)):
    ax.annotate(f'{yv:.1f}%', (xl, yv), textcoords='offset points',
                xytext=(0, 12), ha='center', fontsize=9, fontweight='bold')
ax.set_ylabel('Cumulative Coverage (%)', fontsize=11)
ax.set_xlabel('Enforcement Layer', fontsize=11)
ax.set_title('RQ4d: Cumulative directive coverage by layer', fontsize=12, fontweight='bold')
ax.set_ylim(0, 110)
ax.grid(axis='y', alpha=0.3)
plt.xticks(rotation=15)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig10_rq4d_cumulative_coverage.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 10')

# ===== Fig 11: RQ4e - Cross-event by topic =====
fig, ax = plt.subplots(figsize=(8, 5))
cross_counts = [(t, enf_by_topic[t]['cross_event']) for t in topics if enf_by_topic[t]['cross_event'] > 0]
cross_counts.sort(key=lambda x: x[1], reverse=True)
ct_labels = [SHORT.get(t, t) for t, _ in cross_counts]
ct_vals = [v for _, v in cross_counts]
total_cross = sum(ct_vals)
ax.barh(range(len(ct_labels)), ct_vals[::-1], color='#E74C3C', edgecolor='white')
for i, v in enumerate(ct_vals[::-1]):
    ax.text(v + 1, i, f'{v} ({100 * v / total_cross:.1f}%)', va='center', fontsize=9)
ax.set_yticks(range(len(ct_labels))); ax.set_yticklabels(ct_labels[::-1], fontsize=10)
ax.set_xlabel('Cross-event Directive Count', fontsize=11)
ax.set_title('RQ4e: Where do cross-event directives concentrate?', fontsize=12, fontweight='bold')
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig11_rq4e_cross_event_by_topic.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 11')

# ===== Fig 12: RQ4f - Per-repo enforceability profiles =====
fig, ax = plt.subplots(figsize=(12, 6))
repo_enf.sort(key=lambda r: r['total'], reverse=True)
repo_enf_filtered = [r for r in repo_enf if r['total'] > 0]
x12 = np.arange(len(repo_enf_filtered))
bottom = np.zeros(len(repo_enf_filtered))
for ei, e in enumerate(ENF_LEVELS):
    vals = np.array([r[e] for r in repo_enf_filtered])
    ax.bar(x12, vals, bottom=bottom, color=ENF_COLORS[ei], label=ENF_LABELS[ei], width=1.0, edgecolor='none')
    bottom += vals
ax.set_xlabel('Repositories (sorted by directive count)', fontsize=11)
ax.set_ylabel('Directive Count', fontsize=11)
ax.set_title('RQ4f: Per-repository enforcement profile', fontsize=12, fontweight='bold')
ax.legend(fontsize=9)
ax.set_xlim(-0.5, len(repo_enf_filtered) - 0.5)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig12_rq4f_repo_profiles.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 12')

# ===== Fig 13: RQ4g - Repo requirements =====
fig, ax = plt.subplots(figsize=(6, 4))
n_repos = len([r for r in repo_enf if r['total'] > 0])
has_level = {}
for e in ENF_LEVELS:
    has_level[e] = sum(1 for r in repo_enf if r[e] > 0)
has_all = sum(1 for r in repo_enf if all(r[e] > 0 for e in ENF_LEVELS))
req_labels = ENF_LABELS + ['All four']
req_vals = [100 * has_level[e] / n_repos for e in ENF_LEVELS] + [100 * has_all / n_repos]
req_colors = ENF_COLORS + ['#8E44AD']
ax.barh(req_labels[::-1], req_vals[::-1], color=req_colors[::-1], edgecolor='white')
for i, v in enumerate(req_vals[::-1]):
    ax.text(v + 1, i, f'{v:.0f}%', va='center', fontsize=10, fontweight='bold')
ax.set_xlabel('% of Repositories', fontsize=11)
ax.set_xlim(0, 110)
ax.set_title('RQ4g: What fraction of repos need each layer?', fontsize=12, fontweight='bold')
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig13_rq4g_repo_requirements.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 13')

# ===== Fig 14: Enforcement layers diagram =====
fig, ax = plt.subplots(figsize=(8, 4))
layers_data = [
    ('Semantic-only', 18.9, '#95A5A6', 'Model compliance'),
    ('Content', 37.8, '#3498DB', 'eBPF write hook + linter'),
    ('Per-event', 29.4, '#2ECC71', 'eBPF/LSM hook'),
    ('Cross-event', 13.9, '#E74C3C', 'eBPF + IFC labels'),
]
for i, (name, cov, color, mech) in enumerate(layers_data):
    ax.barh(i, cov, color=color, edgecolor='white', height=0.6)
    ax.text(cov + 1, i, f'{cov}% — {mech}', va='center', fontsize=9)
ax.axvline(x=18.9, color='gray', linestyle=':', linewidth=1, alpha=0.5)
ax.text(19.5, 3.3, 'Tool layer\n(bypassable)', fontsize=8, color='gray', alpha=0.7)
ax.text(19.5, -0.5, 'OS layer\n(unbypassable)', fontsize=8, color='gray', alpha=0.7)
ax.axhline(y=0.65, color='black', linestyle='--', linewidth=1.5, alpha=0.7)
ax.set_yticks(range(4)); ax.set_yticklabels([d[0] for d in layers_data], fontsize=10)
ax.set_xlabel('Directive Coverage (%)', fontsize=11)
ax.set_title('Enforcement layers: mechanism and bypass resistance', fontsize=12, fontweight='bold')
ax.set_xlim(0, 75)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig14_enforcement_layers.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 14')

# ===== Fig 1b: RQ1b - Per-repo directive fraction by lines =====
fig, ax = plt.subplots(figsize=(8, 5))
repo_lines = []
for d in sorted(os.listdir('.')):
    yf = os.path.join(d, 'statements.yaml')
    if not os.path.isfile(yf): continue
    with open(yf) as f:
        data = yaml.safe_load(f)
    if not data or 'statements' not in data: continue
    dl = sl = 0
    for s in data['statements']:
        span = s['lines'][1] - s['lines'][0] if len(s.get('lines', [])) == 2 else 0
        if s.get('type') == 'directive': dl += span
        else: sl += span
    total_l = dl + sl
    if total_l > 0:
        repo_lines.append(100 * dl / total_l)
repo_lines.sort()
colors_1b = ['#FF6B6B' if p >= 50 else '#4ECDC4' for p in repo_lines]
ax.bar(range(len(repo_lines)), repo_lines, color=colors_1b, width=1.0, edgecolor='none')
ax.axhline(y=np.median(repo_lines), color='black', linestyle='--', linewidth=1.5,
           label=f'Median = {np.median(repo_lines):.1f}%')
ax.axhline(y=50, color='gray', linestyle=':', linewidth=1, alpha=0.5)
p_dir = mpatches.Patch(color='#FF6B6B', label='Majority directive (>50%)')
p_desc = mpatches.Patch(color='#4ECDC4', label='Majority description (<50%)')
ax.legend(handles=[p_dir, p_desc, ax.get_lines()[0]], fontsize=9, loc='upper left')
ax.set_xlabel('Repositories (sorted by directive line fraction)', fontsize=11)
ax.set_ylabel('Directive Line Fraction (%)', fontsize=11)
ax.set_title('RQ1b: Directive fraction by line count', fontsize=12, fontweight='bold')
ax.set_ylim(0, 105)
plt.tight_layout()
plt.savefig(os.path.join(outdir, 'fig1b_rq1b_directive_lines.png'), dpi=150, bbox_inches='tight')
plt.close(); print('Fig 1b')

print('All 14 figures saved to docs/tmp/')
