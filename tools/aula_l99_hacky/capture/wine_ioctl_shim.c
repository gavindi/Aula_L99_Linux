#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define HID_IOC_TYPE 'H'
#define HIDIOC_SFEATURE_NR 0x06
#define HIDIOC_GFEATURE_NR 0x07
#define MAX_DUMP_BYTES 1024
#define MAX_LINE 4096
#define MAX_DEVNAME 64
#define FD_CACHE_SIZE 256
#define MAX_ALLOWED 16

typedef struct {
    int fd;
    char dev[MAX_DEVNAME];
    int vid;
    int pid;
    int iface;
} CacheEntry;

typedef struct {
    int vid;
    int pid;
    int iface;
    int wildcard;
} AllowedDev;

static int g_log_fd = -1;
static pthread_once_t g_log_once = PTHREAD_ONCE_INIT;

static void *g_real_ioctl;
static void *g_real_read;
static void *g_real_write;
static void *g_real_close;
static pthread_once_t g_real_once = PTHREAD_ONCE_INIT;

static CacheEntry g_cache[FD_CACHE_SIZE];
static int g_cache_count;
static pthread_rwlock_t g_cache_lock = PTHREAD_RWLOCK_INITIALIZER;

static AllowedDev g_allowed[MAX_ALLOWED];
static int g_allowed_count;
static pthread_once_t g_allowed_once = PTHREAD_ONCE_INIT;

static __thread int g_in_emit;

static long long mono_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void resolve_all(void)
{
    g_real_ioctl = dlsym(RTLD_NEXT, "ioctl");
    g_real_read = dlsym(RTLD_NEXT, "read");
    g_real_write = dlsym(RTLD_NEXT, "write");
    g_real_close = dlsym(RTLD_NEXT, "close");
}

static void open_log(void)
{
    const char *path = getenv("AULA_IOCTL_LOG");
    if (path && *path)
        g_log_fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
}

static void emit(const char *fmt, ...)
{
    char line[MAX_LINE];
    va_list ap;
    ssize_t n;

    if (g_in_emit)
        return;
    g_in_emit = 1;
    if (g_log_fd < 0) {
        g_in_emit = 0;
        return;
    }
    va_start(ap, fmt);
    n = vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    if (n > 0 && n < (ssize_t)sizeof line) {
        line[n++] = '\n';
        syscall(SYS_write, g_log_fd, line, (size_t)n);
        syscall(SYS_write, 2, line, (size_t)n);
    }
    g_in_emit = 0;
}

static void hex_encode(char *out, const void *buf, size_t n)
{
    const unsigned char *p = buf;
    char *q = out;
    size_t i;

    if (n > MAX_DUMP_BYTES)
        n = MAX_DUMP_BYTES;
    for (i = 0; i < n; i++) {
        if (i)
            *q++ = ' ';
        q += sprintf(q, "%02x", p[i]);
    }
    *q = '\0';
}

static void init_allowed(void)
{
    const char *env = getenv("AULA_IOCTL_DEVICES");
    char *copy;
    char *entry;

    if (!env || !*env)
        env = "0c45:800a:3,05ac:024f:3,eeef:268a";
    copy = strdup(env);
    if (!copy)
        return;
    for (entry = strtok(copy, ","); entry; entry = strtok(NULL, ",")) {
        char *sep1;
        char *sep2;
        AllowedDev *allowed;

        if (g_allowed_count >= MAX_ALLOWED)
            break;
        allowed = &g_allowed[g_allowed_count];
        if (strcmp(entry, "*") == 0) {
            allowed->wildcard = 1;
            g_allowed_count++;
            continue;
        }
        sep1 = strchr(entry, ':');
        if (!sep1)
            continue;
        *sep1 = '\0';
        sep2 = strchr(sep1 + 1, ':');
        if (sep2)
            *sep2 = '\0';
        allowed->vid = (int)strtoul(entry, NULL, 16);
        allowed->pid = (int)strtoul(sep1 + 1, NULL, 16);
        allowed->iface = sep2 ? atoi(sep2 + 1) : -1;
        g_allowed_count++;
    }
    free(copy);
}

static int is_allowed(int vid, int pid, int iface)
{
    int i;

    pthread_once(&g_allowed_once, init_allowed);
    for (i = 0; i < g_allowed_count; i++) {
        if (g_allowed[i].wildcard)
            return 1;
        if (g_allowed[i].vid == vid && g_allowed[i].pid == pid
            && (g_allowed[i].iface < 0 || g_allowed[i].iface == iface))
            return 1;
    }
    return 0;
}

static ssize_t read_sysfs(const char *path, char *buf, size_t bufsz)
{
    int fd;
    ssize_t n;

    fd = (int)syscall(SYS_open, path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    n = syscall(SYS_read, fd, buf, bufsz - 1);
    syscall(SYS_close, fd);
    if (n < 0)
        return -1;
    buf[n] = '\0';
    return n;
}

static int parse_id_pair(const char *content, const char *key, char sep,
                         int want, int *first, int *second)
{
    const char *value;
    char seps[2] = {sep, '\0'};
    char *copy;
    char *field;
    int fields[8] = {0};
    int i = 0;
    int need = want + 2;

    value = strstr(content, key);
    if (!value)
        return 0;
    copy = strdup(value + strlen(key));
    if (!copy)
        return 0;
    for (field = strtok(copy, seps); field && i < need;
         field = strtok(NULL, seps)) {
        if (field[0] != '\0')
            fields[i++] = (int)strtoul(field, NULL, 16);
    }
    free(copy);
    if (i < need)
        return 0;
    *first = fields[want];
    *second = fields[want + 1];
    return 1;
}

static int read_interface(const char *devname)
{
    char path[160];
    char buf[16];

    if (strncmp(devname, "/dev/hidraw", sizeof "/dev/hidraw" - 1) != 0)
        return -1;
    snprintf(path, sizeof path, "/sys/class/hidraw/%s/device/../bInterfaceNumber",
             devname + 5);
    if (read_sysfs(path, buf, sizeof buf) <= 0)
        return -1;
    return atoi(buf);
}

static void resolve_ids(const char *devname, int *vid, int *pid, int *iface)
{
    char path[160];
    char buf[1024];

    *vid = 0;
    *pid = 0;
    *iface = -1;
    if (strncmp(devname, "/dev/hidraw", sizeof "/dev/hidraw" - 1) == 0) {
        snprintf(path, sizeof path, "/sys/class/hidraw/%s/device/uevent",
                 devname + 5);
        if (read_sysfs(path, buf, sizeof buf) > 0
            && parse_id_pair(buf, "HID_ID=", ':', 1, vid, pid))
            *iface = read_interface(devname);
    } else if (strncmp(devname, "/dev/ttyACM", sizeof "/dev/ttyACM" - 1) == 0) {
        snprintf(path, sizeof path, "/sys/class/tty/%s/device/uevent",
                 devname + 5);
        if (read_sysfs(path, buf, sizeof buf) <= 0
            || !parse_id_pair(buf, "PRODUCT=", '/', 0, vid, pid)) {
            snprintf(path, sizeof path, "/sys/class/tty/%s/device/../uevent",
                     devname + 5);
            if (read_sysfs(path, buf, sizeof buf) > 0)
                parse_id_pair(buf, "PRODUCT=", '/', 0, vid, pid);
        }
    }
}

static void fd_info(int fd, char *dev, size_t devsz, int *vid, int *pid, int *iface)
{
    int i;

    pthread_rwlock_rdlock(&g_cache_lock);
    for (i = 0; i < g_cache_count; i++) {
        if (g_cache[i].fd == fd) {
            snprintf(dev, devsz, "%s", g_cache[i].dev);
            *vid = g_cache[i].vid;
            *pid = g_cache[i].pid;
            *iface = g_cache[i].iface;
            pthread_rwlock_unlock(&g_cache_lock);
            return;
        }
    }
    pthread_rwlock_unlock(&g_cache_lock);

    snprintf(dev, devsz, "-");
    {
        char path[32];
        char link[MAX_DEVNAME];
        ssize_t n;

        snprintf(path, sizeof path, "/proc/self/fd/%d", fd);
        n = syscall(SYS_readlink, path, link, sizeof link - 1);
        if (n > 0) {
            link[n] = '\0';
            snprintf(dev, devsz, "%s", link);
            resolve_ids(dev, vid, pid, iface);
        }
    }

    pthread_rwlock_wrlock(&g_cache_lock);
    if (g_cache_count < FD_CACHE_SIZE) {
        for (i = 0; i < g_cache_count; i++) {
            if (g_cache[i].fd == fd)
                break;
        }
        if (i == g_cache_count) {
            CacheEntry *entry = &g_cache[g_cache_count];
            entry->fd = fd;
            snprintf(entry->dev, MAX_DEVNAME, "%s", dev);
            entry->vid = *vid;
            entry->pid = *pid;
            entry->iface = *iface;
            g_cache_count++;
        }
    }
    pthread_rwlock_unlock(&g_cache_lock);
}

static void cache_evict(int fd)
{
    int i;

    pthread_rwlock_wrlock(&g_cache_lock);
    for (i = 0; i < g_cache_count; i++) {
        if (g_cache[i].fd == fd) {
            g_cache[i] = g_cache[g_cache_count - 1];
            g_cache_count--;
            break;
        }
    }
    pthread_rwlock_unlock(&g_cache_lock);
}

static void log_rw(int fd, const char *kind, const void *buf, size_t n,
                   ssize_t ret, int err)
{
    char dev[MAX_DEVNAME];
    int vid, pid, iface;
    char hex[MAX_DUMP_BYTES * 3 + 2];

    fd_info(fd, dev, sizeof dev, &vid, &pid, &iface);
    if (!is_allowed(vid, pid, iface))
        return;
    pthread_once(&g_log_once, open_log);
    if (g_log_fd < 0)
        return;
    hex_encode(hex, buf, n);
    emit("RW %lld %ld %ld %d %s %s %zu %s %zd %d",
         mono_ns(), (long)getpid(), (long)syscall(SYS_gettid), fd, dev,
         kind, n, hex, ret, err);
}

int ioctl(int fd, unsigned long request, ...)
{
    void *arg;
    int (*real)(int, unsigned long, ...);
    int ret;
    int saved_errno;
    unsigned long type = (request >> 8) & 0xFF;
    unsigned long nr = request & 0xFF;
    unsigned long size = (request >> 16) & 0x3FFF;
    char dev[MAX_DEVNAME];
    int vid, pid, iface;
    char hex[MAX_DUMP_BYTES * 3 + 2];
    const char *kind;
    va_list ap;

    va_start(ap, request);
    arg = va_arg(ap, void *);
    va_end(ap);

    pthread_once(&g_real_once, resolve_all);
    real = (int (*)(int, unsigned long, ...))g_real_ioctl;

    if (type != HID_IOC_TYPE)
        return real(fd, request, arg);

    fd_info(fd, dev, sizeof dev, &vid, &pid, &iface);
    if (!is_allowed(vid, pid, iface))
        return real(fd, request, arg);

    pthread_once(&g_log_once, open_log);

    saved_errno = errno;
    ret = real(fd, request, arg);
    saved_errno = ret < 0 ? errno : 0;

    if (nr == HIDIOC_SFEATURE_NR)
        kind = "OUT";
    else if (nr == HIDIOC_GFEATURE_NR)
        kind = "IN";
    else
        kind = "META";

    hex[0] = '\0';
    if (size > 0 && size <= MAX_DUMP_BYTES && arg
        && (kind[0] == 'O' || kind[0] == 'I'))
        hex_encode(hex, arg, size);

    emit("I %lld %ld %ld %d %s %lx %s %lu %s %d %d",
         mono_ns(), (long)getpid(), (long)syscall(SYS_gettid), fd, dev,
         request, kind, size, hex, ret, saved_errno);
    errno = saved_errno;
    return ret;
}

ssize_t read(int fd, void *buf, size_t count)
{
    ssize_t ret;
    int saved_errno;

    pthread_once(&g_real_once, resolve_all);
    ret = ((ssize_t (*)(int, void *, size_t))g_real_read)(fd, buf, count);
    saved_errno = errno;
    if (ret > 0)
        log_rw(fd, "read", buf, (size_t)ret, ret, saved_errno);
    errno = saved_errno;
    return ret;
}

ssize_t write(int fd, const void *buf, size_t count)
{
    ssize_t ret;
    int saved_errno;

    pthread_once(&g_real_once, resolve_all);
    ret = ((ssize_t (*)(int, const void *, size_t))g_real_write)(fd, buf, count);
    saved_errno = errno;
    if (ret > 0)
        log_rw(fd, "write", buf, (size_t)ret, ret, saved_errno);
    errno = saved_errno;
    return ret;
}

int close(int fd)
{
    int ret;

    pthread_once(&g_real_once, resolve_all);
    cache_evict(fd);
    ret = ((int (*)(int))g_real_close)(fd);
    return ret;
}
