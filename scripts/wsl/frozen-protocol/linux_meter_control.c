#define _GNU_SOURCE
#include <sys/wait.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <stdint.h>

static void touch(size_t mib) {
    size_t bytes = mib * 1024 * 1024;
    volatile unsigned char *p = malloc(bytes);
    if (!p) _exit(91);
    for (size_t i = 0; i < bytes; i += 4096) p[i] = (unsigned char)i + 1;
    p[bytes - 1] = 1;
    /* Intentionally retain pages until the process exits. */
}
static double cpu_now(void) {
    struct timespec t;
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void busy(double seconds) {
    double start = cpu_now();
    volatile uint64_t value = 1;
    while (cpu_now() - start < seconds) value = value * 6364136223846793005ULL + 1;
}
int main(int argc, char **argv) {
    if (argc != 2) return 64;
    if (!strcmp(argv[1], "child-large-root-small")) {
        pid_t child = fork();
        if (child < 0) return 90;
        if (child == 0) { touch(128); busy(.20); _exit(0); }
        int status;
        if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 92;
        busy(.05);
        touch(32);  /* Allocate the root maximum only at the very end. */
        return 0;
    }
    if (!strcmp(argv[1], "root-late-peak")) {
        busy(.02);
        touch(96);
        _exit(0);
    }
    if (!strcmp(argv[1], "nonzero")) return 7;
    if (!strcmp(argv[1], "timeout-group") || !strcmp(argv[1], "timeout-separate-group")) {
        pid_t child = fork();
        if (child < 0) return 90;
        if (child == 0 && !strcmp(argv[1], "timeout-separate-group") && setpgid(0, 0)) return 93;
        printf("root=%ld child=%ld\n", (long)getpid(), (long)child);
        fflush(stdout);
        for (;;) pause();
    }
    return 64;
}
