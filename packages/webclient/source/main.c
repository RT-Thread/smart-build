/*
 * Copyright (c) 2026 RT-Thread Smart build contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdio.h>

#include <webclient.h>

int main(int argc, char **argv)
{
    struct webclient_session *session;
    int status;

    if (argc != 2)
    {
        printf("usage: webclient <url>\n");
        return 0;
    }

    session = webclient_session_create(WEBCLIENT_HEADER_BUFSZ);
    if (session == RT_NULL)
    {
        printf("webclient: failed to allocate session\n");
        return 1;
    }

    status = webclient_get(session, argv[1]);
    printf("webclient: HTTP status %d\n", status);
    webclient_close(session);

    return status == 200 ? 0 : 1;
}
