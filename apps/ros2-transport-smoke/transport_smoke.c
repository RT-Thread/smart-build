#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <net/if.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

#define TEST_SHM_NAME "/ros2_transport_smoke"
#define TEST_SHM_SIZE 4096
#define TEST_REGULAR_FILE_COUNT 24
#define RT_SMART_FCHMOD_SYSCALL 215

static int fail(const char *operation)
{
    fprintf(stderr, "transport smoke: %s failed: %s\n", operation,
            strerror(errno));
    return -1;
}

static int rt_smart_fchmod(int fd, mode_t mode)
{
    long result = syscall(RT_SMART_FCHMOD_SYSCALL, fd, mode);

    if (result < 0)
    {
        errno = (int)-result;
        return -1;
    }
    return (int)result;
}

static int send_payload(int socket_fd, const struct sockaddr_in *destination,
                        const char *payload)
{
    size_t payload_length = strlen(payload) + 1;

    return sendto(socket_fd, payload, payload_length, 0,
                  (const struct sockaddr *)destination,
                  sizeof(*destination)) == (ssize_t)payload_length ? 0 : -1;
}

static int local_interface_address(int socket_fd, struct in_addr *address)
{
    struct ifreq request;

    memset(&request, 0, sizeof(request));
    strncpy(request.ifr_name, "e0", sizeof(request.ifr_name) - 1);
    if (ioctl(socket_fd, SIOCGIFADDR, &request) < 0)
    {
        return -1;
    }
    *address = ((struct sockaddr_in *)&request.ifr_addr)->sin_addr;
    return 0;
}

static int test_recvmsg(void)
{
    static const char first_payload[] = "sockaddr-storage";
    static const char second_payload[] = "null-name";
    int receiver = -1;
    int sender = -1;
    int flags;
    int result = -1;
    char data[64];
    struct iovec iov;
    struct msghdr message;
    struct sockaddr_in address;
    struct sockaddr_storage source;
    socklen_t address_length = sizeof(address);
    ssize_t received;

    receiver = socket(AF_INET, SOCK_DGRAM, 0);
    sender = socket(AF_INET, SOCK_DGRAM, 0);
    if (receiver < 0 || sender < 0)
    {
        fail("socket");
        goto cleanup;
    }

    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = 0;
    if (bind(receiver, (struct sockaddr *)&address, sizeof(address)) < 0 ||
        getsockname(receiver, (struct sockaddr *)&address, &address_length) < 0)
    {
        fail("bind/getsockname");
        goto cleanup;
    }
    if (local_interface_address(sender, &address.sin_addr) < 0)
    {
        fail("SIOCGIFADDR e0");
        goto cleanup;
    }

    if (send_payload(sender, &address, first_payload) < 0)
    {
        fail("sendto");
        goto cleanup;
    }

    memset(&message, 0, sizeof(message));
    memset(&source, 0, sizeof(source));
    memset(data, 0, sizeof(data));
    iov.iov_base = data;
    iov.iov_len = sizeof(data);
    message.msg_name = &source;
    message.msg_namelen = sizeof(source);
    message.msg_iov = &iov;
    message.msg_iovlen = 1;
    message.msg_control = NULL;
    message.msg_controllen = 0;
    received = recvmsg(receiver, &message, MSG_DONTWAIT);
    if (received != (ssize_t)sizeof(first_payload) ||
        strcmp(data, first_payload) != 0 ||
        source.ss_family != AF_INET ||
        message.msg_namelen != sizeof(struct sockaddr_in))
    {
        errno = EPROTO;
        fail("recvmsg sockaddr_storage");
        goto cleanup;
    }

    if (send_payload(sender, &address, second_payload) < 0)
    {
        fail("sendmsg null-name case");
        goto cleanup;
    }
    memset(&message, 0, sizeof(message));
    memset(data, 0, sizeof(data));
    iov.iov_base = data;
    iov.iov_len = sizeof(data);
    message.msg_name = NULL;
    message.msg_namelen = sizeof(source);
    message.msg_iov = &iov;
    message.msg_iovlen = 1;
    received = recvmsg(receiver, &message, 0);
    if (received != (ssize_t)sizeof(second_payload) ||
        strcmp(data, second_payload) != 0)
    {
        errno = EPROTO;
        fail("recvmsg null name");
        goto cleanup;
    }

    flags = fcntl(receiver, F_GETFL, 0);
    if (flags < 0 || fcntl(receiver, F_SETFL, flags | O_NONBLOCK) < 0)
    {
        fail("fcntl O_NONBLOCK");
        goto cleanup;
    }
    errno = 0;
    received = recvmsg(receiver, &message, MSG_DONTWAIT);
    if (received != -1 || (errno != EAGAIN && errno != EWOULDBLOCK))
    {
        fprintf(stderr,
                "transport smoke: recvmsg nonblocking result=%ld errno=%d\n",
                (long)received, errno);
        errno = EPROTO;
        fail("recvmsg nonblocking error propagation");
        goto cleanup;
    }

    result = 0;

cleanup:
    if (sender >= 0)
    {
        close(sender);
    }
    if (receiver >= 0)
    {
        close(receiver);
    }
    return result;
}

static int test_shared_memory(void)
{
    static const char first_payload[] = "first mapping";
    static const char second_payload[] = "second mapping";
    int first_fd = -1;
    int second_fd = -1;
    int result = -1;
    void *first = MAP_FAILED;
    void *second = MAP_FAILED;
    struct stat directory;

    if (stat("/dev/shm", &directory) < 0 || !S_ISDIR(directory.st_mode))
    {
        errno = ENOENT;
        fail("/dev/shm");
        goto cleanup;
    }

    (void)shm_unlink(TEST_SHM_NAME);
    first_fd = shm_open(TEST_SHM_NAME, O_CREAT | O_EXCL | O_RDWR, 0600);
    if (first_fd < 0 || ftruncate(first_fd, TEST_SHM_SIZE) < 0)
    {
        fail("shm_open/ftruncate");
        goto cleanup;
    }
    second_fd = shm_open(TEST_SHM_NAME, O_RDWR, 0600);
    if (second_fd < 0)
    {
        fail("second shm_open");
        goto cleanup;
    }

    first = mmap(NULL, TEST_SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED,
                 first_fd, 0);
    second = mmap(NULL, TEST_SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED,
                  second_fd, 0);
    if (first == MAP_FAILED || second == MAP_FAILED)
    {
        fail("mmap shared memory");
        goto cleanup;
    }

    memcpy(first, first_payload, sizeof(first_payload));
    if (memcmp(second, first_payload, sizeof(first_payload)) != 0)
    {
        errno = EIO;
        fail("shared memory first-to-second");
        goto cleanup;
    }
    memcpy(second, second_payload, sizeof(second_payload));
    if (memcmp(first, second_payload, sizeof(second_payload)) != 0)
    {
        errno = EIO;
        fail("shared memory second-to-first");
        goto cleanup;
    }

    result = 0;

cleanup:
    if (second != MAP_FAILED)
    {
        munmap(second, TEST_SHM_SIZE);
    }
    if (first != MAP_FAILED)
    {
        munmap(first, TEST_SHM_SIZE);
    }
    if (second_fd >= 0)
    {
        close(second_fd);
    }
    if (first_fd >= 0)
    {
        close(first_fd);
    }
    (void)shm_unlink(TEST_SHM_NAME);
    return result;
}

struct epoll_wait_context
{
    int epoll_fd;
    int event_count;
    struct epoll_event event;
};

static void *wait_for_unix_datagram(void *argument)
{
    struct epoll_wait_context *context = argument;

    memset(&context->event, 0, sizeof(context->event));
    context->event_count = epoll_wait(context->epoll_fd, &context->event,
                                      1, 200);
    return NULL;
}

static int test_unix_datagram_epoll(void)
{
    static const char payload[] = "iceoryx2 notification";
    char received[sizeof(payload)];
    int epoll_fd = -1;
    int event_count;
    int pthread_result;
    int result = -1;
    int sockets[2] = {-1, -1};
    int waiter_started = 0;
    struct epoll_event event;
    struct epoll_wait_context context;
    pthread_t waiter;

    if (socketpair(AF_UNIX, SOCK_DGRAM, 0, sockets) < 0)
    {
        fail("AF_UNIX datagram socketpair");
        goto cleanup;
    }
    epoll_fd = epoll_create1(EPOLL_CLOEXEC);
    if (epoll_fd < 0)
    {
        fail("epoll_create1");
        goto cleanup;
    }

    memset(&event, 0, sizeof(event));
    event.events = EPOLLIN;
    event.data.fd = sockets[1];
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, sockets[1], &event) < 0)
    {
        fail("epoll_ctl AF_UNIX datagram");
        goto cleanup;
    }
    event_count = epoll_wait(epoll_fd, &event, 1, 50);
    if (event_count != 0)
    {
        fprintf(stderr,
                "transport smoke: idle epoll_wait result=%d errno=%d\n",
                event_count, errno);
        errno = EPROTO;
        fail("AF_UNIX idle epoll timeout");
        goto cleanup;
    }

    if (send(sockets[0], payload, sizeof(payload), 0) !=
            (ssize_t)sizeof(payload))
    {
        fail("AF_UNIX datagram send");
        goto cleanup;
    }
    memset(&event, 0, sizeof(event));
    event_count = epoll_wait(epoll_fd, &event, 1, 1000);
    if (event_count != 1 || (event.events & EPOLLIN) == 0 ||
        event.data.fd != sockets[1])
    {
        fprintf(stderr,
                "transport smoke: notified epoll_wait result=%d events=0x%x "
                "fd=%d expected=%d errno=%d\n",
                event_count, event.events, event.data.fd, sockets[1], errno);
        errno = EPROTO;
        fail("AF_UNIX epoll notification");
        goto cleanup;
    }
    if (recv(sockets[1], received, sizeof(received), 0) !=
            (ssize_t)sizeof(payload) ||
        memcmp(received, payload, sizeof(payload)) != 0)
    {
        errno = EIO;
        fail("AF_UNIX datagram receive");
        goto cleanup;
    }

    memset(&context, 0, sizeof(context));
    context.epoll_fd = epoll_fd;
    pthread_result = pthread_create(&waiter, NULL, wait_for_unix_datagram,
                                    &context);
    if (pthread_result != 0)
    {
        errno = pthread_result;
        fail("cross-thread epoll pthread_create");
        goto cleanup;
    }
    waiter_started = 1;
    usleep(20000);
    if (send(sockets[0], payload, sizeof(payload), 0) !=
            (ssize_t)sizeof(payload))
    {
        fail("cross-thread AF_UNIX datagram send");
        goto cleanup;
    }
    pthread_result = pthread_join(waiter, NULL);
    waiter_started = 0;
    if (pthread_result != 0)
    {
        errno = pthread_result;
        fail("cross-thread epoll pthread_join");
        goto cleanup;
    }
    if (context.event_count != 1 ||
        (context.event.events & EPOLLIN) == 0 ||
        context.event.data.fd != sockets[1])
    {
        fprintf(stderr,
                "transport smoke: cross-thread epoll_wait result=%d "
                "events=0x%x fd=%d expected=%d errno=%d\n",
                context.event_count, context.event.events,
                context.event.data.fd, sockets[1], errno);
        errno = EPROTO;
        fail("cross-thread AF_UNIX epoll notification");
        goto cleanup;
    }
    if (recv(sockets[1], received, sizeof(received), 0) !=
            (ssize_t)sizeof(payload) ||
        memcmp(received, payload, sizeof(payload)) != 0)
    {
        errno = EIO;
        fail("cross-thread AF_UNIX datagram receive");
        goto cleanup;
    }

    result = 0;

cleanup:
    if (waiter_started)
    {
        (void)pthread_join(waiter, NULL);
    }
    if (epoll_fd >= 0)
    {
        close(epoll_fd);
    }
    if (sockets[1] >= 0)
    {
        close(sockets[1]);
    }
    if (sockets[0] >= 0)
    {
        close(sockets[0]);
    }
    return result;
}

static int test_regular_file_descriptors(void)
{
    static const char payload[] = "iceoryx2 static storage";
    int descriptors[TEST_REGULAR_FILE_COUNT];
    char paths[TEST_REGULAR_FILE_COUNT][64];
    char content[sizeof(payload)];
    int index;
    int result = -1;
    struct stat status;

    for (index = 0; index < TEST_REGULAR_FILE_COUNT; index++)
    {
        descriptors[index] = -1;
        paths[index][0] = '\0';
    }

    for (index = 0; index < TEST_REGULAR_FILE_COUNT; index++)
    {
        snprintf(paths[index], sizeof(paths[index]),
                 "/tmp/ros2_transport_fd_%02d", index);
        (void)unlink(paths[index]);
        descriptors[index] = open(paths[index], O_CREAT | O_EXCL | O_RDWR,
                                  0700);
        if (descriptors[index] < 0 ||
            rt_smart_fchmod(descriptors[index], 0400) < 0 ||
            fstat(descriptors[index], &status) < 0 ||
            (status.st_mode & 0777) != 0400 ||
            rt_smart_fchmod(descriptors[index], 0700) < 0 ||
            fstat(descriptors[index], &status) < 0 ||
            (status.st_mode & 0777) != 0700)
        {
            fail("regular file open/fchmod/fstat");
            goto cleanup;
        }
    }

    for (index = 0; index < TEST_REGULAR_FILE_COUNT; index++)
    {
        if (write(descriptors[index], NULL, 0) != 0)
        {
            fail("zero-length regular file write");
            goto cleanup;
        }
        if (read(descriptors[index], NULL, 0) != 0)
        {
            fail("zero-length regular file read");
            goto cleanup;
        }
        if (write(descriptors[index], payload, sizeof(payload)) !=
                (ssize_t)sizeof(payload) ||
            lseek(descriptors[index], 0, SEEK_SET) != 0 ||
            read(descriptors[index], content, sizeof(content)) !=
                (ssize_t)sizeof(content) ||
            memcmp(content, payload, sizeof(payload)) != 0)
        {
            fprintf(stderr,
                    "transport smoke: regular file fd=%d index=%d errno=%d\n",
                    descriptors[index], index, errno);
            errno = EIO;
            fail("regular file write/read");
            goto cleanup;
        }
    }

    result = 0;

cleanup:
    for (index = 0; index < TEST_REGULAR_FILE_COUNT; index++)
    {
        if (descriptors[index] >= 0)
        {
            close(descriptors[index]);
        }
        if (paths[index][0] != '\0')
        {
            (void)unlink(paths[index]);
        }
    }
    return result;
}

static int wait_for_success(pid_t child, const char *operation)
{
    int status;
    pid_t waited;

    waited = waitpid(child, &status, 0);
    if (waited != child || !WIFEXITED(status) || WEXITSTATUS(status) != 0)
    {
        fprintf(stderr,
                "transport smoke: %s child=%ld waited=%ld status=0x%x errno=%d\n",
                operation, (long)child, (long)waited, status, errno);
        errno = ECHILD;
        return fail(operation);
    }
    return 0;
}

static int test_record_locks(void)
{
    static const char path[] = "/tmp/ros2_transport_record_lock";
    int fd = -1;
    int result = -1;
    pid_t child;
    pid_t parent = getpid();
    struct flock lock;

    (void)unlink(path);
    fd = open(path, O_CREAT | O_EXCL | O_RDWR, 0600);
    if (fd < 0)
    {
        fail("record lock open");
        goto cleanup;
    }

    memset(&lock, 0, sizeof(lock));
    lock.l_type = F_WRLCK;
    lock.l_whence = SEEK_SET;
    if (fcntl(fd, F_SETLK, &lock) < 0)
    {
        fail("record lock parent F_SETLK");
        goto cleanup;
    }

    child = fork();
    if (child < 0)
    {
        fail("record lock fork conflict");
        goto cleanup;
    }
    if (child == 0)
    {
        struct flock query = lock;
        int query_result;

        query_result = fcntl(fd, F_GETLK, &query);
        if (query_result < 0 || query.l_type != F_WRLCK ||
            query.l_pid != parent)
        {
            dprintf(STDERR_FILENO,
                    "transport smoke: child F_GETLK result=%d errno=%d "
                    "type=%d pid=%ld parent=%ld\n",
                    query_result, errno, (int)query.l_type,
                    (long)query.l_pid, (long)parent);
            _exit(10);
        }
        errno = 0;
        if (fcntl(fd, F_SETLK, &lock) != -1 ||
            (errno != EAGAIN && errno != EACCES))
        {
            dprintf(STDERR_FILENO,
                    "transport smoke: child conflicting F_SETLK errno=%d\n",
                    errno);
            _exit(11);
        }
        _exit(0);
    }
    if (wait_for_success(child, "record lock conflict") < 0)
    {
        goto cleanup;
    }

    lock.l_type = F_UNLCK;
    if (fcntl(fd, F_SETLK, &lock) < 0)
    {
        fail("record lock parent unlock");
        goto cleanup;
    }

    child = fork();
    if (child < 0)
    {
        fail("record lock fork acquire");
        goto cleanup;
    }
    if (child == 0)
    {
        lock.l_type = F_WRLCK;
        if (fcntl(fd, F_SETLK, &lock) < 0)
        {
            _exit(12);
        }
        _exit(0);
    }
    if (wait_for_success(child, "record lock acquire after unlock") < 0)
    {
        goto cleanup;
    }

    result = 0;

cleanup:
    if (fd >= 0)
    {
        close(fd);
    }
    (void)unlink(path);
    return result;
}

int main(void)
{
    if (test_recvmsg() < 0 || test_shared_memory() < 0 ||
        test_unix_datagram_epoll() < 0 ||
        test_regular_file_descriptors() < 0 || test_record_locks() < 0)
    {
        return 1;
    }
    puts("transport smoke: PASS");
    return 0;
}
