// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause
/* Copyright (c) 2026 eunomia-bpf org. */
//
// ActPlane in-kernel taint enforcer. Each hook propagates taint and evaluates
// the compiled rules; the ONLY event emitted is a TAINT_VIOLATION, via the
// single emit_violation() function, when a rule matches.

#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>
#include "process.h"
#include "taint_engine.bpf.h"

char LICENSE[] SEC("license") = "Dual BSD/GPL";

struct {
	__uint(type, BPF_MAP_TYPE_RINGBUF);
	__uint(max_entries, 256 * 1024);
} rb SEC(".maps");

/* The one and only output channel. */
static __always_inline void emit_violation(pid_t pid, unsigned int rule_id,
					   const char *target, u32 conn_ip)
{
	struct task_struct *task = (struct task_struct *)bpf_get_current_task();
	struct event *v = bpf_ringbuf_reserve(&rb, sizeof(*v), 0);
	if (!v)
		return;
	v->type = EVENT_TYPE_TAINT_VIOLATION;
	v->pid = pid;
	v->ppid = BPF_CORE_READ(task, real_parent, tgid);
	v->timestamp_ns = bpf_ktime_get_ns();
	v->taint_rule_id = rule_id;
	v->conn_ip = conn_ip;
	v->taint_label = te_labels(pid);
	bpf_get_current_comm(&v->comm, sizeof(v->comm));
	v->filename[0] = '\0';
	if (target)
		bpf_probe_read_kernel_str(&v->filename, sizeof(v->filename), target);
	bpf_ringbuf_submit(v, 0);
}

SEC("tp/sched/sched_process_fork")
int handle_fork(struct trace_event_raw_sched_process_fork *ctx)
{
	te_fork(ctx->parent_pid, ctx->child_pid);
	return 0;
}

SEC("tp/sched/sched_process_exec")
int handle_exec(struct trace_event_raw_sched_process_exec *ctx)
{
	pid_t pid = bpf_get_current_pid_tgid() >> 32;
	struct task_struct *task = (struct task_struct *)bpf_get_current_task();
	char comm[TAINT_PAT_LEN] = {}; /* >= pattern len so matchers stay in-bounds */
	char argv[TAINT_ARGV_CAP];
	char fname[MAX_FILENAME_LEN];
	unsigned fname_off;
	int alen = 0, rid;

	bpf_get_current_comm(&comm, TASK_COMM_LEN);
	te_exec_update(pid, comm);

	/* read argv blob (NUL-separated) for @arg matching */
	struct mm_struct *mm = BPF_CORE_READ(task, mm);
	unsigned long a0 = BPF_CORE_READ(mm, arg_start);
	unsigned long a1 = BPF_CORE_READ(mm, arg_end);
	unsigned long len = a1 - a0;
	if (len > TAINT_ARGV_CAP - 1)
		len = TAINT_ARGV_CAP - 1;
	if (len > 0 && bpf_probe_read_user(argv, len, (void *)a0) == 0)
		alen = (int)len;

	rid = te_check(pid, TOP_EXEC, comm, argv, alen);
	if (rid >= 0) {
		fname_off = ctx->__data_loc_filename & 0xFFFF;
		bpf_probe_read_str(fname, sizeof(fname), (void *)ctx + fname_off);
		emit_violation(pid, rid, fname, 0);
	}
	return 0;
}

SEC("tp/sched/sched_process_exit")
int handle_exit(struct trace_event_raw_sched_process_template *ctx)
{
	u64 id = bpf_get_current_pid_tgid();
	pid_t pid = id >> 32;
	if (pid != (u32)id)
		return 0;
	te_exit(pid);
	return 0;
}

/* open flag bits (not always in vmlinux.h) */
#ifndef O_WRONLY
#define O_WRONLY 00000001
#endif
#ifndef O_RDWR
#define O_RDWR 00000002
#endif
#ifndef O_CREAT
#define O_CREAT 00000100
#endif
#ifndef O_TRUNC
#define O_TRUNC 00001000
#endif
#define TAINT_WRITE_FLAGS (O_WRONLY | O_RDWR | O_CREAT | O_TRUNC)

static __always_inline void do_open(pid_t pid, const char *upath, u64 flags)
{
	char path[MAX_FILENAME_LEN];
	int rid;
	if (bpf_probe_read_user_str(path, sizeof(path), upath) < 0)
		return;
	te_read(pid, path); /* read(p,f): proc absorbs file labels + file source */
	if (flags & TAINT_WRITE_FLAGS) {
		te_write_flow(pid, path); /* write(p,f): file inherits writer labels */
		rid = te_check(pid, TOP_WRITE, path, 0, 0);
		if (rid >= 0) {
			emit_violation(pid, rid, path, 0);
			return;
		}
	}
	rid = te_check(pid, TOP_OPEN, path, 0, 0);
	if (rid >= 0)
		emit_violation(pid, rid, path, 0);
}

SEC("tp/syscalls/sys_enter_openat")
int trace_openat(struct trace_event_raw_sys_enter *ctx)
{
	do_open(bpf_get_current_pid_tgid() >> 32, (const char *)ctx->args[1], ctx->args[2]);
	return 0;
}

SEC("tp/syscalls/sys_enter_open")
int trace_open(struct trace_event_raw_sys_enter *ctx)
{
	do_open(bpf_get_current_pid_tgid() >> 32, (const char *)ctx->args[0], ctx->args[1]);
	return 0;
}

static __always_inline void do_mutate(pid_t pid, const char *upath)
{
	char path[MAX_FILENAME_LEN];
	int rid;
	if (bpf_probe_read_user_str(path, sizeof(path), upath) < 0)
		return;
	te_write_flow(pid, path); /* proc -> file propagation */
	rid = te_check(pid, TOP_WRITE, path, 0, 0);
	if (rid >= 0)
		emit_violation(pid, rid, path, 0);
}

SEC("tp/syscalls/sys_enter_unlink")
int trace_unlink(struct trace_event_raw_sys_enter *ctx)
{
	do_mutate(bpf_get_current_pid_tgid() >> 32, (const char *)ctx->args[0]);
	return 0;
}
SEC("tp/syscalls/sys_enter_unlinkat")
int trace_unlinkat(struct trace_event_raw_sys_enter *ctx)
{
	do_mutate(bpf_get_current_pid_tgid() >> 32, (const char *)ctx->args[1]);
	return 0;
}
SEC("tp/syscalls/sys_enter_rename")
int trace_rename(struct trace_event_raw_sys_enter *ctx)
{
	do_mutate(bpf_get_current_pid_tgid() >> 32, (const char *)ctx->args[1]);
	return 0;
}
SEC("tp/syscalls/sys_enter_renameat")
int trace_renameat(struct trace_event_raw_sys_enter *ctx)
{
	do_mutate(bpf_get_current_pid_tgid() >> 32, (const char *)ctx->args[3]);
	return 0;
}
SEC("tp/syscalls/sys_enter_renameat2")
int trace_renameat2(struct trace_event_raw_sys_enter *ctx)
{
	do_mutate(bpf_get_current_pid_tgid() >> 32, (const char *)ctx->args[3]);
	return 0;
}

/* connect: numeric IPv4 matching (compiler lowers host/IP patterns to net+mask;
 * no in-kernel string formatting, so no verifier-rejected pointer arithmetic).
 * The reported IP is formatted by the userspace loader from conn_ip. */
SEC("tp/syscalls/sys_enter_connect")
int trace_connect(struct trace_event_raw_sys_enter *ctx)
{
	pid_t pid = bpf_get_current_pid_tgid() >> 32;
	const void *uaddr = (const void *)ctx->args[1];
	int rid;
	u16 family = 0;

	if (bpf_probe_read_user(&family, sizeof(family), uaddr) < 0)
		return 0;
	if (family != 2) /* AF_INET */
		return 0;
	struct sockaddr_in sa = {};
	if (bpf_probe_read_user(&sa, sizeof(sa), uaddr) < 0)
		return 0;
	u32 ip = sa.sin_addr.s_addr; /* network byte order */

	te_add_labels(pid, te_endp_src_ip(ip));   /* endpoint source taints connector */
	te_connect_flow(ip, pid);                 /* proc -> endpoint */
	rid = te_connect_check(pid, ip);
	if (rid >= 0)
		emit_violation(pid, rid, 0, ip);
	return 0;
}
