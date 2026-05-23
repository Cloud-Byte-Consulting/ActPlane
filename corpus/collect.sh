#!/bin/bash
# ActPlane agent-policy corpus collector.
# Finds popular *code* projects (not awesome-lists/doc repos) in the AI-agent space
# that ship a CLAUDE.md or AGENTS.md, sorted by stars desc, and saves one folder per
# repo: the raw file(s) + meta.json (repo, stars, license, topics, per-file blob/commit
# SHA, content hash, retrieval date). Reproducible: records every API query in queries.log.
# Usage: bash corpus/collect.sh [TARGET_HITS]
set -u
cd "$(dirname "$0")"
OUT="."                       # corpus/ dir
TARGET="${1:-50}"
PROBE_CAP=320                 # how many candidates to probe before giving up
CAND="$(mktemp)"; SEEDM="$(mktemp)"
QLOG="$OUT/queries.log"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
: > "$QLOG"
echo "collection_started=$NOW" >> "$QLOG"

emit() { # repos search -> NDJSON of candidate metadata
  gh api -X GET search/repositories -f q="$1" -f sort=stars -f order=desc -f per_page=100 \
    --jq '.items[] | {full_name, stars: .stargazers_count, forks: .forks_count, issues: .open_issues_count, created_at, language, license: (.license.key // null), fork, archived, pushed_at, default_branch, html_url, description, topics}' \
    2>>"$QLOG"
}

echo ">> gathering candidates via topic/keyword search"
QUERIES=(
  'topic:ai-agent stars:>300'
  'topic:ai-agents stars:>300'
  'topic:llm-agent stars:>300'
  'topic:autonomous-agents stars:>300'
  'topic:agent stars:>1500'
  'topic:llm stars:>4000'
  'topic:mcp stars:>800'
  'topic:coding-agent stars:>100'
  'topic:ai-coding stars:>300'
  'AI agent framework stars:>3000'
  'coding agent stars:>2000'
  'llm agent in:name,description stars:>2500'
)
for q in "${QUERIES[@]}"; do
  echo "search q=[$q] at $(date -u +%H:%M:%S)" >> "$QLOG"
  emit "$q" >> "$CAND"
  sleep 2.2   # stay under search rate limit (30/min)
done

# Known-popular agent code projects, probed regardless of the name filter.
SEEDS=(
  OpenHands/OpenHands paul-gauthier/aider Aider-AI/aider cline/cline
  Significant-Gravitas/AutoGPT geekan/MetaGPT AntonOsika/gpt-engineer
  continuedev/continue block/goose princeton-nlp/SWE-agent SWE-agent/SWE-agent
  langchain-ai/langchain run-llama/llama_index crewAIInc/crewAI langgenius/dify
  microsoft/autogen OpenInterpreter/open-interpreter anthropics/claude-code
  RooCodeInc/Roo-Code All-Hands-AI/OpenHands stitionai/devika OpenDevin/OpenDevin
  yetone/avante.nvim sourcegraph/cody sst/opencode getzep/graphiti
  microsoft/vscode QwenLM/qwen-code google-gemini/gemini-cli musistudio/claude-code-router
  browser-use/browser-use mannaandpoem/OpenManus FoundationAgents/OpenManus
  punkpeye/fastmcp modelcontextprotocol/servers
)
echo ">> fetching seed metadata"
for s in "${SEEDS[@]}"; do
  gh api "repos/$s" --jq '{full_name, stars: .stargazers_count, language, license: (.license.key // null), fork, archived, pushed_at, default_branch, html_url, description, topics, seed: true}' \
    2>>"$QLOG" >> "$SEEDM"
done

# Merge, dedup by full_name (keep seed flag if any), sort by stars desc.
RANKED="$(mktemp)"
cat "$CAND" "$SEEDM" | jq -s 'map(select(.full_name)) | group_by(.full_name) | map(add) | sort_by(-(.stars // 0))' > "$RANKED"
echo "candidates_unique=$(jq 'length' "$RANKED")" >> "$QLOG"
echo ">> $(jq 'length' "$RANKED") unique candidates ranked by stars"

# Code-project filter: drop doc/aggregator repos unless seeded.
EXCL='awesome|curated|list-of|^list$|prompt|cheat.?sheet|handbook|tutorial|roadmap|^guide|guides|papers?|reading|^book|course|interview|leetcode|^resources?|collection'
is_code_project() { # $1 name(lower) $2 language $3 seed
  [ "$3" = "true" ] && return 0
  case "$2" in null|Markdown|"") return 1;; esac
  echo "$1" | grep -Eiq "$EXCL" && return 1
  return 0
}

probe_file() { # full path dir family ; returns 0 if saved
  local full="$1" path="$2" dir="$3" family="$4"
  local meta sha size raw lc lcsha lcdate csha
  meta="$(gh api "repos/$full/contents/$path" --jq '.sha+" "+(.size|tostring)' 2>/dev/null)" || return 1
  sha="${meta%% *}"; size="${meta##* }"
  mkdir -p "$dir"
  if ! gh api "repos/$full/contents/$path" -H "Accept: application/vnd.github.raw" > "$dir/$path" 2>/dev/null; then
    rm -f "$dir/$path"; return 1
  fi
  lc="$(gh api "repos/$full/commits?path=$path&per_page=1" --jq '.[0].sha+" "+.[0].commit.committer.date' 2>/dev/null)"
  lcsha="${lc%% *}"; lcdate="${lc##* }"
  csha="$(sha256sum "$dir/$path" | cut -d' ' -f1)"
  # stash one file-record line for later assembly
  jq -nc --arg family "$family" --arg path "$path" --arg blob "$sha" --arg size "$size" \
        --arg lcsha "$lcsha" --arg lcdate "$lcdate" --arg csha "$csha" \
        --arg raw "https://raw.githubusercontent.com/$full/${lcsha:-HEAD}/$path" \
    '{family:$family,path:$path,blob_sha:$blob,byte_size:($size|tonumber),last_commit_sha:$lcsha,last_commit_date:$lcdate,content_sha256:$csha,raw_url:$raw}' \
    >> "$dir/.files.ndjson"
  return 0
}

echo ">> probing for CLAUDE.md / AGENTS.md (target $TARGET hits)"
hits=0; probed=0
MANIFEST="$OUT/manifest.jsonl"; : > "$MANIFEST"
while read -r row; do
  [ "$hits" -ge "$TARGET" ] && break
  [ "$probed" -ge "$PROBE_CAP" ] && break
  probed=$((probed+1))
  full="$(jq -r '.full_name' <<<"$row")"
  name="$(jq -r '.full_name|ascii_downcase' <<<"$row")"
  lang="$(jq -r '.language // "null"' <<<"$row")"
  seed="$(jq -r '.seed // false' <<<"$row")"
  is_code_project "$name" "$lang" "$seed" || continue
  dir="$OUT/${full//\//__}"
  rm -f "$dir/.files.ndjson"
  got=0
  probe_file "$full" "CLAUDE.md" "$dir" "CLAUDE.md" && got=1
  probe_file "$full" "AGENTS.md" "$dir" "AGENTS.md" && got=1
  if [ "$got" = 1 ]; then
    files="$(jq -s '.' "$dir/.files.ndjson")"; rm -f "$dir/.files.ndjson"
    jq -n --argjson r "$row" --argjson files "$files" --arg now "$NOW" \
      '{repo:$r.full_name, owner:($r.full_name|split("/")[0]), name:($r.full_name|split("/")[1]),
        stars:$r.stars, language:$r.language, license:$r.license, fork:$r.fork, archived:$r.archived,
        pushed_at:$r.pushed_at, default_branch:$r.default_branch, html_url:$r.html_url,
        description:$r.description, topics:$r.topics, seed:($r.seed//false),
        domain:"", retrieved_at:$now, files:$files}' > "$dir/meta.json"
    jq -c '.' "$dir/meta.json" >> "$MANIFEST"
    hits=$((hits+1))
    printf '  [%2d] %-45s ★%-7s %s\n' "$hits" "$full" "$(jq -r '.stars' <<<"$row")" "$(jq -r '[.files[].family]|join(",")' "$dir/meta.json")"
  else
    rmdir "$dir" 2>/dev/null
  fi
done < <(jq -c '.[]' "$RANKED")

echo "collection_finished=$(date -u +%Y-%m-%dT%H:%M:%SZ) hits=$hits probed=$probed" >> "$QLOG"
echo ">> done: $hits repos saved (probed $probed candidates). manifest=$MANIFEST"
rm -f "$CAND" "$SEEDM" "$RANKED" "$SEEDM"
