#include <errno.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX];
    uint32_t executable_size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &executable_size) != 0) {
        fprintf(stderr, "Unable to locate the application executable.\n");
        return 1;
    }

    char resolved[PATH_MAX];
    if (realpath(executable, resolved) == NULL) {
        fprintf(stderr, "Unable to resolve the application path: %s\n", strerror(errno));
        return 1;
    }

    /* executable -> MacOS -> Contents -> .app -> project root */
    for (int i = 0; i < 4; ++i) {
        char *separator = strrchr(resolved, '/');
        if (separator == NULL) {
            fprintf(stderr, "Unexpected application path.\n");
            return 1;
        }
        *separator = '\0';
    }

    char python[PATH_MAX];
    char run_script[PATH_MAX];
    if (snprintf(python, sizeof(python), "%s/.venv/bin/python", resolved) >= (int)sizeof(python) ||
        snprintf(run_script, sizeof(run_script), "%s/run.py", resolved) >= (int)sizeof(run_script)) {
        fprintf(stderr, "Application path is too long.\n");
        return 1;
    }

    if (chdir(resolved) != 0) {
        fprintf(stderr, "Unable to open the project directory: %s\n", strerror(errno));
        return 1;
    }

    char **child_argv = calloc((size_t)argc + 2, sizeof(char *));
    if (child_argv == NULL) {
        fprintf(stderr, "Unable to allocate launcher arguments.\n");
        return 1;
    }
    child_argv[0] = python;
    child_argv[1] = run_script;
    for (int i = 1; i < argc; ++i) {
        child_argv[i + 1] = argv[i];
    }

    execv(python, child_argv);
    fprintf(stderr, "Unable to start PDF Converter: %s\n", strerror(errno));
    free(child_argv);
    return 1;
}
