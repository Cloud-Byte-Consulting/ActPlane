// SPDX-License-Identifier: MIT
// Copyright (c) 2026 eunomia-bpf org.
//
// Unit tests for the ActPlane taint matching predicates (taint.h) — the exact
// logic the eBPF engine uses for sources, sinks, masks, conditions and @arg.

#include <stdio.h>
#include <string.h>
#include <stdbool.h>

#include "taint.h"

#define RESET "\033[0m"
#define GREEN "\033[32m"
#define RED   "\033[31m"
static int passed = 0, failed = 0;
static void check(bool c, const char *name)
{
	if (c) { printf("[" GREEN "PASS" RESET "] %s\n", name); passed++; }
	else   { printf("[" RED "FAIL" RESET "] %s\n", name); failed++; }
}

static void test_streq(void)
{
	check(taint_streq("git", "git") == 1, "streq: equal");
	check(taint_streq("git", "ssh") == 0, "streq: different");
	check(taint_streq("git", "gitk") == 0, "streq: prefix is not equal");
	check(taint_streq("", "") == 1, "streq: both empty");
}

static void test_prefix(void)
{
	check(taint_prefix("/etc/secrets/key", "/etc/secrets") == 1, "prefix: under");
	check(taint_prefix("/etc/passwd", "/etc/secrets") == 0, "prefix: sibling");
	check(taint_prefix("/etc", "/etc/secrets") == 0, "prefix: shorter");
	check(taint_prefix("10.0.0.5", "10.0.0.") == 1, "prefix: ip");
	check(taint_prefix("8.8.8.8", "10.0.0.") == 0, "prefix: ip miss");
	check(taint_prefix("/x", "") == 0, "prefix: empty never matches");
}

static void test_match(void)
{
	check(taint_match(TAINT_MATCH_EXACT, "git", "git") == 1, "match: exact hit");
	check(taint_match(TAINT_MATCH_EXACT, "gitk", "git") == 0, "match: exact miss");
	check(taint_match(TAINT_MATCH_PREFIX, "/a/b", "/a") == 1, "match: prefix hit");
	check(taint_match(TAINT_MATCH_SUFFIX, "/home/u/.env", ".env") == 1, "match: suffix hit");
	check(taint_match(TAINT_MATCH_SUFFIX, "/home/u/app.py", ".env") == 0, "match: suffix miss");
	check(taint_match(TAINT_MATCH_SUFFIX, "api.internal", ".internal") == 1, "match: host suffix");
	check(taint_match(TAINT_MATCH_ANY, "literally anything", "") == 1, "match: any");
}

static void test_mask(void)
{
	// req = A&B (bits 0,1), forbid = C (bit 2)
	unsigned long long req = 0b011, forbid = 0b100;
	check(taint_mask_ok(0b011, req, forbid) == 1, "mask: A&B, no C -> ok (violation fires)");
	check(taint_mask_ok(0b001, req, forbid) == 0, "mask: only A -> req unmet");
	check(taint_mask_ok(0b111, req, forbid) == 0, "mask: A&B but C set -> forbidden");
	check(taint_mask_ok(0b011, 0, 0) == 1, "mask: empty req/forbid always ok");
	// 'not REVIEWED' style: req=UNTRUST(bit0), forbid=REVIEWED(bit1)
	check(taint_mask_ok(0b01, 0b01, 0b10) == 1, "mask: UNTRUST & not REVIEWED -> fire");
	check(taint_mask_ok(0b11, 0b01, 0b10) == 0, "mask: endorsed REVIEWED -> suppressed");
}

static void test_arg(void)
{
	// argv blob is NUL-separated tokens
	const char *av = "git\0push\0--force";
	int n = 3 + 1 + 4 + 1 + 7; // "git" "push" "--force"
	check(taint_arg_match(av, n, "push") == 1, "arg: push present");
	check(taint_arg_match(av, n, "--force") == 1, "arg: --force present");
	check(taint_arg_match(av, n, "commit") == 0, "arg: commit absent");
	check(taint_arg_match(av, n, "pus") == 0, "arg: partial token not matched");
	check(taint_arg_match(av, n, "") == 1, "arg: empty token matches anything");
	const char *av2 = "git\0commit";
	check(taint_arg_match(av2, 3 + 1 + 6, "commit") == 1, "arg: commit present");
	check(taint_arg_match(av2, 3 + 1 + 6, "push") == 0, "arg: push absent");
}

int main(void)
{
	printf("=== ActPlane taint predicate tests ===\n");
	test_streq();
	test_prefix();
	test_match();
	test_mask();
	test_arg();
	printf("\n%d passed, %d failed\n", passed, failed);
	return failed == 0 ? 0 : 1;
}
