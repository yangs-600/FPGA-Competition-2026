#define _GNU_SOURCE
#include <sys/ptrace.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <time.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* External root-only RSS meter. No Yosys/ABC modification and no fork tracing.
 * argv: result.json logfile timeout_seconds absolute_program [args...]
 * Wall includes fork, exec-stop handling, execution, exit-stop reading, reap.
 * wait4 CPU includes descendant CPU propagated by the tracee's own waits.
 */
static volatile sig_atomic_t interrupted;
static void on_signal(int signum) { interrupted = signum; }
static double now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return -1;
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static double timeval_seconds(struct timeval t) { return t.tv_sec + t.tv_usec / 1e6; }
static void json_string(FILE *f, const char *s) {
    fputc('"', f);
    for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
        if (*p == '"' || *p == '\\') { fputc('\\', f); fputc(*p, f); }
        else if (*p < 32) fprintf(f, "\\u%04x", *p);
        else fputc(*p, f);
    }
    fputc('"', f);
}
static int read_root_peak(pid_t pid, unsigned long long *peak_kib, double *cpu, int *cpu_clock_precise) {
    char path[96], line[512];
    snprintf(path, sizeof(path), "/proc/%ld/status", (long)pid);
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    int found = 0;
    while (fgets(line, sizeof(line), f)) {
        if (sscanf(line, "VmHWM: %llu kB", peak_kib) == 1) found = 1;
    }
    fclose(f);
    if (!found || !*peak_kib) { errno = ENODATA; return -1; }
    clockid_t id;
    struct timespec t;
    if (clock_getcpuclockid(pid, &id) == 0 && clock_gettime(id, &t) == 0) {
        *cpu = t.tv_sec + t.tv_nsec / 1e9;
        *cpu_clock_precise = 1;
        return 0;
    }
    /* Explicit auxiliary fallback, never used for the main wait4 CPU metric. */
    snprintf(path, sizeof(path), "/proc/%ld/stat", (long)pid);
    f = fopen(path, "r");
    if (!f) return -1;
    char text[8192];
    if (!fgets(text, sizeof(text), f)) { fclose(f); return -1; }
    fclose(f);
    char *tail = strrchr(text, ')');
    if (!tail || tail[1] != ' ') { errno = EINVAL; return -1; }
    char *save = NULL, *token = strtok_r(tail + 2, " ", &save);
    unsigned long long user = 0, system = 0;
    for (int field = 3; token; token = strtok_r(NULL, " ", &save), ++field) {
        if (field == 14) user = strtoull(token, NULL, 10);
        if (field == 15) {
            system = strtoull(token, NULL, 10);
            long ticks = sysconf(_SC_CLK_TCK);
            if (ticks <= 0) { errno = EINVAL; return -1; }
            *cpu = (double)(user + system) / ticks;
            *cpu_clock_precise = 0;
            return 0;
        }
    }
    errno = EINVAL;
    return -1;
}
static int group_exists(pid_t pgid) {
    if (kill(-pgid, 0) == 0 || errno == EPERM) return 1;
    return errno == ESRCH ? 0 : -1;
}
static int cleanup(pid_t child) {
    if (child <= 0) return 0;
    kill(-child, SIGKILL);
    kill(child, SIGKILL);
    double deadline = now() + 5;
    for (;;) {
        int status;
        pid_t got = waitpid(-1, &status, WNOHANG | __WALL);
        if (got > 0) {
            if (WIFSTOPPED(status)) ptrace(PTRACE_CONT, got, NULL, (void *)(intptr_t)SIGKILL);
            continue;
        }
        if (got < 0 && errno == ECHILD) break;
        if (now() > deadline) break;
        struct timespec pause = {0, 1000000};
        nanosleep(&pause, NULL);
    }
    return group_exists(child) == 0;
}

int main(int argc, char **argv) {
    if (argc < 5 || argv[4][0] != '/') {
        fprintf(stderr, "usage: linux_root_meter result.json logfile timeout absolute_program [args...]\n");
        return 64;
    }
    char *end = NULL;
    double timeout = strtod(argv[3], &end);
    if (!end || *end || !isfinite(timeout) || timeout <= 0 || timeout > 3600) return 64;
    int result_fd = open(argv[1], O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
    if (result_fd < 0) { perror("exclusive result creation"); return 65; }
    FILE *result = fdopen(result_fd, "w");
    if (!result) { close(result_fd); return 65; }
    int log_fd = open(argv[2], O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
    if (log_fd < 0) { perror("exclusive log creation"); fclose(result); return 65; }
    struct sigaction action = {0};
    action.sa_handler = on_signal;
    sigemptyset(&action.sa_mask);
    sigaction(SIGALRM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    const char *error = "";
    int error_number = 0, exit_code = -1, exec_seen = 0, exit_seen = 0;
    int final_reaped = 0, clean = 0, cpu_clock_precise = 0, signal_exits = 0;
    unsigned long long peak_kib = 0;
    double root_cpu = 0, start = 0, finish = 0, exec_stop_seconds = 0, exit_stop_seconds = 0;
    struct rusage usage = {0};
    if (prctl(PR_SET_CHILD_SUBREAPER, 1) < 0) {
        error = "PR_SET_CHILD_SUBREAPER failed"; error_number = errno;
        goto output;
    }
    struct itimerval alarm_time = {0};
    alarm_time.it_value.tv_sec = (time_t)timeout;
    alarm_time.it_value.tv_usec = (suseconds_t)((timeout - floor(timeout)) * 1e6);
    if (!alarm_time.it_value.tv_sec && !alarm_time.it_value.tv_usec) alarm_time.it_value.tv_usec = 1;
    if (setitimer(ITIMER_REAL, &alarm_time, NULL)) {
        error = "setitimer failed"; error_number = errno;
        goto output;
    }
    start = now();
    pid_t child = fork();
    if (child == 0) {
        if (setpgid(0, 0) || prctl(PR_SET_PDEATHSIG, SIGKILL)) _exit(124);
        int null_fd = open("/dev/null", O_RDONLY);
        if (null_fd < 0 || dup2(null_fd, STDIN_FILENO) < 0 || dup2(log_fd, STDOUT_FILENO) < 0 || dup2(log_fd, STDERR_FILENO) < 0) _exit(124);
        if (null_fd > STDERR_FILENO) close(null_fd);
        close(log_fd);
        close(result_fd);
        if (ptrace(PTRACE_TRACEME, 0, NULL, NULL) < 0) { perror("PTRACE_TRACEME"); _exit(125); }
        execv(argv[4], &argv[4]);
        perror("execv");
        _exit(126);
    }
    if (child < 0) {
        error = "fork failed"; error_number = errno;
        goto output;
    }
    /* Child also sets its own group; EACCES can mean it has already exec'd. */
    if (setpgid(child, child) && errno != EACCES && errno != ESRCH) {
        error = "parent setpgid failed"; error_number = errno;
    }
    close(log_fd); log_fd = -1;
    while (!*error) {
        if (interrupted) { error = "interrupted or timed out"; break; }
        int status = 0;
        struct rusage observed = {0};
        pid_t got = wait4(child, &status, __WALL, &observed);
        if (got < 0) {
            if (errno == EINTR) continue;
            error = "wait4 failed"; error_number = errno; break;
        }
        if (WIFEXITED(status) || WIFSIGNALED(status)) {
            usage = observed;
            finish = now();
            final_reaped = 1;
            exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
            signal_exits = WIFSIGNALED(status) ? WTERMSIG(status) : 0;
            break;
        }
        if (!WIFSTOPPED(status)) { error = "unexpected wait status"; break; }
        int event = (unsigned int)status >> 16;
        if (!exec_seen) {
            if (WSTOPSIG(status) != SIGTRAP || event != 0) { error = "missing initial exec SIGTRAP"; break; }
            exec_seen = 1;
            exec_stop_seconds = now() - start;
            if (ptrace(PTRACE_SETOPTIONS, child, NULL, (void *)(uintptr_t)(PTRACE_O_TRACEEXIT | PTRACE_O_EXITKILL))) {
                error = "PTRACE_SETOPTIONS failed"; error_number = errno; break;
            }
            if (ptrace(PTRACE_CONT, child, NULL, NULL)) { error = "PTRACE_CONT after exec failed"; error_number = errno; break; }
        } else if (event == PTRACE_EVENT_EXIT) {
            if (exit_seen) { error = "duplicate root exit event"; break; }
            exit_stop_seconds = now() - start;
            if (read_root_peak(child, &peak_kib, &root_cpu, &cpu_clock_precise)) {
                error = "root VmHWM/CPU unavailable at PTRACE_EVENT_EXIT"; error_number = errno; break;
            }
            exit_seen = 1;
            if (ptrace(PTRACE_CONT, child, NULL, NULL)) { error = "PTRACE_CONT after exit event failed"; error_number = errno; break; }
        } else if (event != 0) {
            error = "unexpected ptrace event"; break;
        } else {
            /* Preserve ordinary signal delivery, rather than suppressing it. */
            if (ptrace(PTRACE_CONT, child, NULL, (void *)(intptr_t)WSTOPSIG(status))) {
                error = "PTRACE_CONT signal delivery failed"; error_number = errno; break;
            }
        }
    }
    alarm_time.it_value.tv_sec = alarm_time.it_value.tv_usec = 0;
    setitimer(ITIMER_REAL, &alarm_time, NULL);
    if (!final_reaped || *error) {
        clean = cleanup(child);
        if (!finish) finish = now();
    } else {
        clean = group_exists(child) == 0;
        if (!clean) {
            error = "descendants survived root exit";
            clean = cleanup(child);
        }
    }
    if (!*error && (!exec_seen || !exit_seen || !peak_kib)) error = "missing exec/exit peak evidence";
    if (!*error && exit_code != 0) error = "tracee returned nonzero";

output:
    if (log_fd >= 0) close(log_fd);
    fprintf(result, "{\n\"schema\":1,\"meter_status\":");
    json_string(result, *error ? "FAIL" : "PASS");
    fprintf(result, ",\"error\":"); json_string(result, error);
    fprintf(result, ",\"error_number\":%d,\"exit_code\":%d,\"signal\":%d,\"interrupted_signal\":%d,\n", error_number, exit_code, signal_exits, (int)interrupted);
    fprintf(result, "\"wall_seconds\":%.9f,\"cpu_seconds\":%.9f,\"root_cpu_seconds\":%.9f,\n",
            finish > start && start > 0 ? finish - start : 0,
            timeval_seconds(usage.ru_utime) + timeval_seconds(usage.ru_stime), root_cpu);
    fprintf(result, "\"root_cpu_source\":\"%s\",\"root_cpu_scope\":\"root only through PTRACE_EVENT_EXIT; excludes final exit cleanup\",\n",
            cpu_clock_precise ? "clock_getcpuclockid/clock_gettime" : "proc_pid_stat_ticks_fallback");
    fprintf(result, "\"peak_working_set_bytes\":%llu,\"root_vmhwm_kib\":%llu,\"wait4_maxrss_kib_diagnostic_only\":%ld,\n",
            peak_kib * 1024ULL, peak_kib, usage.ru_maxrss);
    fprintf(result, "\"exec_stop_seconds\":%.9f,\"exit_stop_seconds\":%.9f,\"exec_stop_seen\":%s,\"exit_stop_seen\":%s,\n",
            exec_stop_seconds, exit_stop_seconds, exec_seen ? "true" : "false", exit_seen ? "true" : "false");
    fprintf(result, "\"final_reaped\":%s,\"process_group_empty\":%s,\"memory_counter_reads\":%d,\"final_memory_counter_read\":%s,\n",
            final_reaped ? "true" : "false", clean ? "true" : "false", exit_seen, exit_seen ? "true" : "false");
    fprintf(result, "\"total_job_processes\":null,\"active_job_processes\":%s,\"limit_terminated_processes\":%d,\n",
            clean ? "0" : "null", interrupted ? 1 : 0);
    fprintf(result, "\"compatibility_fields\":\"No Windows Job exists. total_job_processes unavailable; active_job_processes=0 only denotes the owned process group is empty. peak_working_set_bytes is Linux root VmHWM in bytes.\",\n");
    fprintf(result, "\"cpu_scope\":\"wait4 user+system of root plus descendants whose usage root reaped; root must wait for ABC\",\"root_minor_faults_plus_reaped_children\":%ld,\"root_major_faults_plus_reaped_children\":%ld\n}\n", usage.ru_minflt, usage.ru_majflt);
    if (fclose(result)) return 70;
    return *error ? 2 : 0;
}
