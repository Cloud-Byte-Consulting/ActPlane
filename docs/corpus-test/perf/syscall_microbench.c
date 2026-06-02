#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <netinet/in.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

struct options {
    const char *op;
    long iterations;
    long warmup;
    const char *tmpdir;
    const char *raw_path;
    int cpu;
    int payload_bytes;
};

struct bench_ctx {
    char open_path[4096];
    char write_path[4096];
    int write_fd;
    char *payload;
    int payload_bytes;
    struct sockaddr_in connect_addr;
};

struct stats {
    uint64_t min;
    uint64_t max;
    uint64_t p50;
    uint64_t p90;
    uint64_t p95;
    uint64_t p99;
    uint64_t p999;
    long double mean;
};

typedef int (*sample_fn)(struct bench_ctx *ctx, uint64_t *latency_ns);

static void usage(const char *argv0)
{
    fprintf(stderr,
            "usage: %s [--op all|open|write|connect|fork|exec] "
            "[--iterations N] [--warmup N] [--tmpdir DIR] [--raw PATH] "
            "[--cpu CPU] [--payload-bytes N]\n",
            argv0);
    exit(2);
}

static uint64_t now_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &ts) != 0) {
        perror("clock_gettime");
        exit(1);
    }
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a;
    uint64_t y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

static uint64_t percentile(const uint64_t *sorted, long n, long double pct)
{
    if (n <= 0)
        return 0;
    long double pos = (pct / 100.0L) * (long double)(n - 1);
    long idx = (long)(pos + 0.5L);
    if (idx < 0)
        idx = 0;
    if (idx >= n)
        idx = n - 1;
    return sorted[idx];
}

static struct stats compute_stats(uint64_t *samples, long n)
{
    struct stats out = {0};
    qsort(samples, (size_t)n, sizeof(samples[0]), cmp_u64);
    out.min = samples[0];
    out.max = samples[n - 1];
    out.p50 = percentile(samples, n, 50.0L);
    out.p90 = percentile(samples, n, 90.0L);
    out.p95 = percentile(samples, n, 95.0L);
    out.p99 = percentile(samples, n, 99.0L);
    out.p999 = percentile(samples, n, 99.9L);

    long double sum = 0;
    for (long i = 0; i < n; i++)
        sum += (long double)samples[i];
    out.mean = sum / (long double)n;
    return out;
}

static int set_cpu(int cpu)
{
    if (cpu < 0)
        return 0;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0)
        return -errno;
    return 0;
}

static int ensure_dir(const char *path)
{
    if (mkdir(path, 0700) == 0 || errno == EEXIST)
        return 0;
    return -errno;
}

static int wait_child(pid_t pid)
{
    int status = 0;
    for (;;) {
        if (waitpid(pid, &status, 0) >= 0)
            break;
        if (errno != EINTR)
            return -errno;
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
        return -ECHILD;
    return 0;
}

static int sample_open(struct bench_ctx *ctx, uint64_t *latency_ns)
{
    uint64_t start = now_ns();
    int fd = open(ctx->open_path, O_RDONLY | O_CLOEXEC);
    uint64_t end = now_ns();
    if (fd < 0)
        return -errno;
    close(fd);
    *latency_ns = end - start;
    return 0;
}

static int sample_write(struct bench_ctx *ctx, uint64_t *latency_ns)
{
    if (lseek(ctx->write_fd, 0, SEEK_SET) < 0)
        return -errno;
    uint64_t start = now_ns();
    ssize_t n = write(ctx->write_fd, ctx->payload, (size_t)ctx->payload_bytes);
    uint64_t end = now_ns();
    if (n != ctx->payload_bytes)
        return n < 0 ? -errno : -EIO;
    *latency_ns = end - start;
    return 0;
}

static int sample_connect(struct bench_ctx *ctx, uint64_t *latency_ns)
{
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (fd < 0)
        return -errno;
    uint64_t start = now_ns();
    int rc = connect(fd, (struct sockaddr *)&ctx->connect_addr,
                     sizeof(ctx->connect_addr));
    uint64_t end = now_ns();
    int saved = errno;
    close(fd);
    if (rc != 0)
        return -saved;
    *latency_ns = end - start;
    return 0;
}

static int sample_fork(struct bench_ctx *ctx, uint64_t *latency_ns)
{
    (void)ctx;
    uint64_t start = now_ns();
    pid_t pid = fork();
    if (pid == 0)
        _exit(0);
    if (pid < 0)
        return -errno;
    int rc = wait_child(pid);
    uint64_t end = now_ns();
    if (rc != 0)
        return rc;
    *latency_ns = end - start;
    return 0;
}

static int sample_exec(struct bench_ctx *ctx, uint64_t *latency_ns)
{
    (void)ctx;
    uint64_t start = now_ns();
    pid_t pid = fork();
    if (pid == 0) {
        char *const argv[] = {"/bin/true", NULL};
        char *const envp[] = {NULL};
        execve("/bin/true", argv, envp);
        _exit(127);
    }
    if (pid < 0)
        return -errno;
    int rc = wait_child(pid);
    uint64_t end = now_ns();
    if (rc != 0)
        return rc;
    *latency_ns = end - start;
    return 0;
}

static sample_fn fn_for_op(const char *op)
{
    if (strcmp(op, "open") == 0)
        return sample_open;
    if (strcmp(op, "write") == 0)
        return sample_write;
    if (strcmp(op, "connect") == 0)
        return sample_connect;
    if (strcmp(op, "fork") == 0)
        return sample_fork;
    if (strcmp(op, "exec") == 0)
        return sample_exec;
    return NULL;
}

static int write_raw(const char *path, const char *op, const uint64_t *samples, long n)
{
    if (!path)
        return 0;
    FILE *f = fopen(path, "a");
    if (!f)
        return -errno;
    for (long i = 0; i < n; i++)
        fprintf(f, "%s,%ld,%" PRIu64 "\n", op, i, samples[i]);
    fclose(f);
    return 0;
}

static int run_one(struct bench_ctx *ctx, const char *op, long iterations,
                   long warmup, const char *raw_path)
{
    sample_fn fn = fn_for_op(op);
    if (!fn) {
        fprintf(stderr, "unknown op: %s\n", op);
        return -EINVAL;
    }
    uint64_t ignored = 0;
    for (long i = 0; i < warmup; i++) {
        int rc = fn(ctx, &ignored);
        if (rc != 0)
            return rc;
    }

    uint64_t *samples = calloc((size_t)iterations, sizeof(samples[0]));
    uint64_t *sorted = calloc((size_t)iterations, sizeof(sorted[0]));
    if (!samples || !sorted)
        return -ENOMEM;
    for (long i = 0; i < iterations; i++) {
        int rc = fn(ctx, &samples[i]);
        if (rc != 0) {
            free(samples);
            free(sorted);
            return rc;
        }
    }
    int raw_rc = write_raw(raw_path, op, samples, iterations);
    memcpy(sorted, samples, (size_t)iterations * sizeof(sorted[0]));
    struct stats st = compute_stats(sorted, iterations);
    printf("{\"benchmark\":\"syscall_microbench\",\"op\":\"%s\","
           "\"iterations\":%ld,\"warmup\":%ld,\"unit\":\"ns\","
           "\"min_ns\":%" PRIu64 ",\"mean_ns\":%.3Lf,"
           "\"p50_ns\":%" PRIu64 ",\"p90_ns\":%" PRIu64 ","
           "\"p95_ns\":%" PRIu64 ",\"p99_ns\":%" PRIu64 ","
           "\"p999_ns\":%" PRIu64 ",\"max_ns\":%" PRIu64 "}\n",
           op, iterations, warmup, st.min, st.mean, st.p50, st.p90, st.p95,
           st.p99, st.p999, st.max);
    fflush(stdout);
    free(samples);
    free(sorted);
    return raw_rc;
}

static int init_ctx(struct bench_ctx *ctx, const struct options *opts)
{
    memset(ctx, 0, sizeof(*ctx));
    snprintf(ctx->open_path, sizeof(ctx->open_path), "%s/open_target", opts->tmpdir);
    snprintf(ctx->write_path, sizeof(ctx->write_path), "%s/write_target", opts->tmpdir);
    int fd = open(ctx->open_path, O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC, 0600);
    if (fd < 0)
        return -errno;
    if (write(fd, "x", 1) != 1) {
        int saved = errno;
        close(fd);
        return -saved;
    }
    close(fd);

    ctx->payload_bytes = opts->payload_bytes;
    ctx->payload = malloc((size_t)ctx->payload_bytes);
    if (!ctx->payload)
        return -ENOMEM;
    memset(ctx->payload, 'A', (size_t)ctx->payload_bytes);
    ctx->write_fd = open(ctx->write_path, O_CREAT | O_TRUNC | O_RDWR | O_CLOEXEC, 0600);
    if (ctx->write_fd < 0)
        return -errno;

    memset(&ctx->connect_addr, 0, sizeof(ctx->connect_addr));
    ctx->connect_addr.sin_family = AF_INET;
    ctx->connect_addr.sin_port = htons(9);
    ctx->connect_addr.sin_addr.s_addr = htonl(0x7f000001u);
    return 0;
}

static void free_ctx(struct bench_ctx *ctx)
{
    if (ctx->write_fd > 0)
        close(ctx->write_fd);
    free(ctx->payload);
}

int main(int argc, char **argv)
{
    char tmp_template[] = "/tmp/actplane-perf-XXXXXX";
    struct options opts = {
        .op = "all",
        .iterations = 100000,
        .warmup = 1000,
        .tmpdir = NULL,
        .raw_path = NULL,
        .cpu = -1,
        .payload_bytes = 4096,
    };

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--op") == 0 && i + 1 < argc) {
            opts.op = argv[++i];
        } else if (strcmp(argv[i], "--iterations") == 0 && i + 1 < argc) {
            opts.iterations = atol(argv[++i]);
        } else if (strcmp(argv[i], "--warmup") == 0 && i + 1 < argc) {
            opts.warmup = atol(argv[++i]);
        } else if (strcmp(argv[i], "--tmpdir") == 0 && i + 1 < argc) {
            opts.tmpdir = argv[++i];
        } else if (strcmp(argv[i], "--raw") == 0 && i + 1 < argc) {
            opts.raw_path = argv[++i];
        } else if (strcmp(argv[i], "--cpu") == 0 && i + 1 < argc) {
            opts.cpu = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--payload-bytes") == 0 && i + 1 < argc) {
            opts.payload_bytes = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--json") == 0) {
            /* JSON is the only output mode. Kept for explicit runner commands. */
        } else {
            usage(argv[0]);
        }
    }
    if (opts.iterations <= 0 || opts.warmup < 0 || opts.payload_bytes <= 0)
        usage(argv[0]);

    if (!opts.tmpdir) {
        opts.tmpdir = mkdtemp(tmp_template);
        if (!opts.tmpdir) {
            perror("mkdtemp");
            return 1;
        }
    } else if (ensure_dir(opts.tmpdir) != 0) {
        perror("mkdir tmpdir");
        return 1;
    }

    int rc = set_cpu(opts.cpu);
    if (rc != 0) {
        errno = -rc;
        perror("sched_setaffinity");
        return 1;
    }

    struct bench_ctx ctx;
    rc = init_ctx(&ctx, &opts);
    if (rc != 0) {
        errno = -rc;
        perror("init");
        return 1;
    }

    const char *ops[] = {"open", "write", "connect", "fork", "exec"};
    if (strcmp(opts.op, "all") == 0) {
        for (size_t i = 0; i < sizeof(ops) / sizeof(ops[0]); i++) {
            rc = run_one(&ctx, ops[i], opts.iterations, opts.warmup, opts.raw_path);
            if (rc != 0)
                break;
        }
    } else {
        rc = run_one(&ctx, opts.op, opts.iterations, opts.warmup, opts.raw_path);
    }

    free_ctx(&ctx);
    if (rc != 0) {
        errno = -rc;
        perror("benchmark");
        return 1;
    }
    return 0;
}
