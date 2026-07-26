/*
 * Copyright (c) 2026 RT-Thread Smart build contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdio.h>
#include <string.h>

#include <rtthread.h>
#include <webnet.h>

static void print_usage(void)
{
    printf("usage: webnet [--help]\n");
}

int main(int argc, char **argv)
{
    int status;

    if ((argc == 2) && (strcmp(argv[1], "--help") == 0))
    {
        print_usage();
        return 0;
    }
    if (argc != 1)
    {
        print_usage();
        return 1;
    }

    status = webnet_init();
    if (status != 0)
    {
        printf("webnet: failed to initialize server\n");
        return 1;
    }

    printf("webnet: listening on port %d root %s\n",
           webnet_get_port(), webnet_get_root());
    for (;;)
    {
        (void)rt_thread_mdelay(1000);
    }
}
