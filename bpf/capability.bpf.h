/* SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause */
/* Copyright (c) 2026 eunomia-bpf org. */
#ifndef __CAPABILITY_BPF_H
#define __CAPABILITY_BPF_H

/*
 * Minimal runtime admission path for policy deltas.
 *
 * User space can enqueue cap_delta_request records into cap_req. The kernel
 * drains them from normal enforcement hooks, checks only masks/scope/target,
 * and applies accepted monotonic deltas to cap_state. No DSL/YAML/roles live
 * here.
 */

#define AUTH_TARGET_SELF  (1ULL << 0)
#define AUTH_TARGET_CHILD (1ULL << 1)

#define AUTH_ADD_RESTRICTION (1ULL << 0)
#define AUTH_ADD_LABEL       (1ULL << 1)
#define AUTH_REQUIRE_GATE    (1ULL << 2)
#define AUTH_NARROW_SCOPE    (1ULL << 3)

#define CAP_STAT_ACCEPT 0
#define CAP_STAT_REJECT 1
#define CAP_STAT_DRAIN  2
#define CAP_STAT_DROP   3

struct cap_state {
	__u32 parent;
	__u32 scope_id;
	__u64 labels;
	__u64 authority_mask;
	__u64 target_mask;
	__u64 restrict_mask;
	__u64 gate_mask;
	__u64 label_mask;
};

struct cap_delta_request {
	pid_t caller_pid;
	__u32 target_id;
	__u32 new_scope_id;
	__u64 required_mask;
	__u64 add_restrict_mask;
	__u64 add_label_mask;
	__u64 add_gate_mask;
};

struct {
	__uint(type, BPF_MAP_TYPE_USER_RINGBUF);
	__uint(max_entries, 64 * 1024);
} cap_req SEC(".maps");

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__uint(max_entries, 4096);
	__type(key, __u32);
	__type(value, struct cap_state);
} cap_state SEC(".maps");

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__uint(max_entries, 16384);
	__type(key, pid_t);
	__type(value, __u32);
} cap_task SEC(".maps");

struct {
	__uint(type, BPF_MAP_TYPE_ARRAY);
	__uint(max_entries, 4);
	__type(key, __u32);
	__type(value, __u64);
} cap_stats SEC(".maps");

static __always_inline void cap_count(__u32 slot)
{
	__u64 *v = bpf_map_lookup_elem(&cap_stats, &slot);
	if (v)
		(*v)++;
}

static __always_inline __u64 cap_required_mask(const struct cap_delta_request *r)
{
	__u64 mask = r->required_mask;

	if (r->add_restrict_mask)
		mask |= AUTH_ADD_RESTRICTION;
	if (r->add_label_mask)
		mask |= AUTH_ADD_LABEL;
	if (r->add_gate_mask)
		mask |= AUTH_REQUIRE_GATE;
	if (r->new_scope_id)
		mask |= AUTH_NARROW_SCOPE;
	return mask;
}

static __always_inline int cap_scope_subset(__u32 new_scope, __u32 old_scope)
{
	if (!new_scope)
		return 1;
	if (!old_scope)
		return 1;
	return new_scope >= old_scope;
}

static __always_inline __u64
cap_target_mask(__u32 caller, __u32 target, const struct cap_state *dst)
{
	__u64 mask = 0;

	if (caller == target)
		mask |= AUTH_TARGET_SELF;
	if (dst->parent == caller)
		mask |= AUTH_TARGET_CHILD;
	return mask;
}

static __always_inline int cap_apply_request(const struct cap_delta_request *r)
{
	__u32 *caller = bpf_map_lookup_elem(&cap_task, &r->caller_pid);
	if (!caller)
		return -1;

	struct cap_state *src = bpf_map_lookup_elem(&cap_state, caller);
	struct cap_state *dst = bpf_map_lookup_elem(&cap_state, &r->target_id);
	if (!src || !dst)
		return -1;

	__u64 target_mask = cap_target_mask(*caller, r->target_id, dst);
	if (!(target_mask & src->target_mask))
		return -1;
	if (cap_required_mask(r) & ~src->authority_mask)
		return -1;
	if (r->add_label_mask & ~src->label_mask)
		return -1;
	if (!cap_scope_subset(r->new_scope_id, dst->scope_id))
		return -1;

	struct cap_state next = *dst;
	next.restrict_mask |= r->add_restrict_mask;
	next.labels |= r->add_label_mask;
	next.gate_mask |= r->add_gate_mask;
	if (r->new_scope_id)
		next.scope_id = r->new_scope_id;
	bpf_map_update_elem(&cap_state, &r->target_id, &next, BPF_EXIST);
	return 0;
}

/* ── Hot-reload protocol ────────────────────────────────────────────
 *
 * Policy reload messages share the cap_req user ring buffer. They are
 * distinguished from capability deltas by a negative value in the first
 * __s32 field (caller_pid is always > 0 for real deltas).  The BPF drain
 * callback peeks the tag, then reads the appropriately-sized payload and
 * applies it to the writable ts_updates / ts_rules / ts_counts maps.
 *
 * Reload sequence (from userspace):
 *   1. RELOAD_COUNTS(n_rules=0, n_updates=0)   — quiesce engine
 *   2. RELOAD_UPDATE(i, entry) × n_updates      — populate updates
 *   3. RELOAD_RULE(i, entry)   × n_rules         — populate rules
 *   4. RELOAD_COUNTS(n_rules, n_updates)          — activate
 */

#define CAP_REQ_RELOAD_UPDATE  (-1)
#define CAP_REQ_RELOAD_RULE    (-2)
#define CAP_REQ_RELOAD_COUNTS  (-3)

struct cap_reload_update {
	__s32 tag;
	__u32 index;
	struct taint_update entry;
};

struct cap_reload_rule {
	__s32 tag;
	__u32 index;
	struct taint_rule entry;
};

struct cap_reload_counts {
	__s32 tag;
	__u32 n_rules;
	__u32 n_updates;
	__u32 _pad;
};

struct cap_drain_ctx {
	pid_t current_pid;
};

static long cap_request_cb(struct bpf_dynptr *dynptr, void *data)
{
	const __s32 *tag = bpf_dynptr_data(dynptr, 0, sizeof(__s32));
	if (!tag) {
		cap_count(CAP_STAT_DROP);
		return 0;
	}

	if (*tag == CAP_REQ_RELOAD_UPDATE) {
		const struct cap_reload_update *r =
			bpf_dynptr_data(dynptr, 0, sizeof(*r));
		if (!r || r->index >= MAX_TAINT_UPDATES) {
			cap_count(CAP_STAT_DROP);
			return 0;
		}
		struct taint_update tmp;
		__builtin_memcpy(&tmp, &r->entry, sizeof(tmp));
		__u32 idx = r->index;
		bpf_map_update_elem(&ts_updates, &idx, &tmp, BPF_ANY);
		cap_count(CAP_STAT_ACCEPT);
		return 0;
	}
	if (*tag == CAP_REQ_RELOAD_RULE) {
		const struct cap_reload_rule *r =
			bpf_dynptr_data(dynptr, 0, sizeof(*r));
		if (!r || r->index >= MAX_TAINT_RULES) {
			cap_count(CAP_STAT_DROP);
			return 0;
		}
		struct taint_rule tmp;
		__builtin_memcpy(&tmp, &r->entry, sizeof(tmp));
		__u32 idx = r->index;
		bpf_map_update_elem(&ts_rules, &idx, &tmp, BPF_ANY);
		cap_count(CAP_STAT_ACCEPT);
		return 0;
	}
	if (*tag == CAP_REQ_RELOAD_COUNTS) {
		const struct cap_reload_counts *r =
			bpf_dynptr_data(dynptr, 0, sizeof(*r));
		if (!r) {
			cap_count(CAP_STAT_DROP);
			return 0;
		}
		__u32 slot0 = 0, slot1 = 1;
		__u32 nr = r->n_rules, nu = r->n_updates;
		bpf_map_update_elem(&ts_counts, &slot0, &nr, BPF_ANY);
		bpf_map_update_elem(&ts_counts, &slot1, &nu, BPF_ANY);
		cap_count(CAP_STAT_ACCEPT);
		return 0;
	}

	/* Normal capability delta request (caller_pid > 0). */
	{
		const struct cap_delta_request *r;
		struct cap_drain_ctx *ctx = data;

		r = bpf_dynptr_data(dynptr, 0, sizeof(*r));
		if (!r) {
			cap_count(CAP_STAT_DROP);
			return 0;
		}
		if (r->caller_pid != ctx->current_pid) {
			cap_count(CAP_STAT_DROP);
			return 0;
		}
		if (cap_apply_request(r) == 0)
			cap_count(CAP_STAT_ACCEPT);
		else
			cap_count(CAP_STAT_REJECT);
	}
	return 0;
}

static __always_inline void cap_drain_current(void)
{
	struct cap_drain_ctx ctx = {
		.current_pid = bpf_get_current_pid_tgid() >> 32,
	};
	bpf_user_ringbuf_drain(&cap_req, cap_request_cb, &ctx, 0);
	cap_count(CAP_STAT_DRAIN);
}

static __always_inline __u64 cap_labels_for_pid(pid_t pid)
{
	__u32 *target = bpf_map_lookup_elem(&cap_task, &pid);
	if (!target)
		return 0;
	struct cap_state *p = bpf_map_lookup_elem(&cap_state, target);
	if (!p)
		return 0;
	return p->labels | p->restrict_mask;
}

static __always_inline void cap_fork(pid_t ppid, pid_t cpid)
{
	__u32 *target = bpf_map_lookup_elem(&cap_task, &ppid);
	if (target)
		bpf_map_update_elem(&cap_task, &cpid, target, BPF_ANY);
}

static __always_inline void cap_exit(pid_t pid)
{
	bpf_map_delete_elem(&cap_task, &pid);
}

#endif /* __CAPABILITY_BPF_H */
