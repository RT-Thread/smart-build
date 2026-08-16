/*
 * Copyright(c) 2006 to 2021 ZettaScale Technology and others
 *
 * SPDX-License-Identifier: EPL-2.0 OR BSD-3-Clause
 */

#include <assert.h>
#include <errno.h>
#include <net/if.h>
#include <stdbool.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

#include "dds/ddsrt/heap.h"
#include "dds/ddsrt/ifaddrs.h"
#include "dds/ddsrt/retcode.h"
#include "dds/ddsrt/string.h"

#define RT_SMART_MAX_INTERFACES 16

extern const int *const os_supp_afs;

static bool
family_requested(const int *afs, int family)
{
  for (size_t i = 0; afs[i] != DDSRT_AF_TERM; i++) {
    if (afs[i] == family) {
      return true;
    }
  }
  return false;
}

static dds_return_t
error_from_errno(void)
{
  switch (errno) {
    case EACCES:
      return DDS_RETCODE_NOT_ALLOWED;
    case ENOMEM:
    case ENOBUFS:
      return DDS_RETCODE_OUT_OF_RESOURCES;
    default:
      return DDS_RETCODE_ERROR;
  }
}

static int
query_interface(int fd, const char *name, unsigned long request, struct ifreq *ifr)
{
  memset(ifr, 0, sizeof(*ifr));
  ddsrt_strlcpy(ifr->ifr_name, name, sizeof(ifr->ifr_name));
  return ioctl(fd, request, ifr);
}

static dds_return_t
copy_interface(ddsrt_ifaddrs_t **result, int fd, const char *name)
{
  struct ifreq address;
  struct ifreq netmask;
  struct ifreq flags;
  struct ifreq index;
  ddsrt_ifaddrs_t *ifa;
  struct sockaddr_in broadcast;
  const struct sockaddr_in *ip;
  const struct sockaddr_in *mask;

  if (query_interface(fd, name, SIOCGIFADDR, &address) < 0 ||
      query_interface(fd, name, SIOCGIFNETMASK, &netmask) < 0 ||
      query_interface(fd, name, SIOCGIFFLAGS, &flags) < 0) {
    return error_from_errno();
  }

  address.ifr_addr.sa_family = AF_INET;
  netmask.ifr_netmask.sa_family = AF_INET;
  ifa = ddsrt_calloc_s(1, sizeof(*ifa));
  if (ifa == NULL) {
    return DDS_RETCODE_OUT_OF_RESOURCES;
  }

  ifa->name = ddsrt_strdup(name);
  ifa->addr = ddsrt_memdup(&address.ifr_addr, sizeof(struct sockaddr_in));
  ifa->netmask = ddsrt_memdup(&netmask.ifr_netmask, sizeof(struct sockaddr_in));
  if (ifa->name == NULL || ifa->addr == NULL || ifa->netmask == NULL) {
    ddsrt_freeifaddrs(ifa);
    return DDS_RETCODE_OUT_OF_RESOURCES;
  }

  ifa->flags = (uint32_t)(uint16_t)flags.ifr_flags;
  if (strcmp(name, "lo") == 0) {
    ifa->flags |= IFF_LOOPBACK;
    ifa->type = DDSRT_IFTYPE_UNKNOWN;
  } else {
    ifa->flags |= IFF_BROADCAST | IFF_MULTICAST;
    ifa->type = DDSRT_IFTYPE_WIRED;
  }

  if (query_interface(fd, name, SIOCGIFINDEX, &index) == 0 && index.ifr_ifindex > 0) {
    ifa->index = (uint32_t)index.ifr_ifindex;
  } else {
    ifa->index = 1;
  }

  ip = (const struct sockaddr_in *)ifa->addr;
  mask = (const struct sockaddr_in *)ifa->netmask;
  memset(&broadcast, 0, sizeof(broadcast));
  broadcast.sin_family = AF_INET;
  broadcast.sin_addr.s_addr = ip->sin_addr.s_addr | ~mask->sin_addr.s_addr;
  ifa->broadaddr = ddsrt_memdup(&broadcast, sizeof(broadcast));
  if (ifa->broadaddr == NULL) {
    ddsrt_freeifaddrs(ifa);
    return DDS_RETCODE_OUT_OF_RESOURCES;
  }

  *result = ifa;
  return DDS_RETCODE_OK;
}

dds_return_t
ddsrt_getifaddrs(ddsrt_ifaddrs_t **ifap, const int *afs)
{
  struct ifreq interfaces[RT_SMART_MAX_INTERFACES];
  struct ifconf config;
  ddsrt_ifaddrs_t *root = NULL;
  ddsrt_ifaddrs_t **tail = &root;
  dds_return_t result = DDS_RETCODE_OK;
  int fd;
  size_t count;

  assert(ifap != NULL);
  *ifap = NULL;
  if (afs == NULL) {
    afs = os_supp_afs;
  }
  if (!family_requested(afs, AF_INET)) {
    return DDS_RETCODE_OK;
  }

  fd = socket(AF_INET, SOCK_DGRAM, 0);
  if (fd < 0) {
    return error_from_errno();
  }

  memset(interfaces, 0, sizeof(interfaces));
  config.ifc_len = (int)sizeof(interfaces);
  config.ifc_req = interfaces;
  if (ioctl(fd, SIOCGIFCONF, &config) < 0) {
    result = error_from_errno();
    goto done;
  }

  count = (size_t)config.ifc_len / sizeof(interfaces[0]);
  if (count > RT_SMART_MAX_INTERFACES) {
    count = RT_SMART_MAX_INTERFACES;
  }
  for (size_t i = 0; i < count; i++) {
    ddsrt_ifaddrs_t *ifa = NULL;
    result = copy_interface(&ifa, fd, interfaces[i].ifr_name);
    if (result != DDS_RETCODE_OK) {
      goto done;
    }
    *tail = ifa;
    tail = &ifa->next;
  }

done:
  close(fd);
  if (result == DDS_RETCODE_OK) {
    *ifap = root;
  } else {
    ddsrt_freeifaddrs(root);
  }
  return result;
}

dds_return_t
ddsrt_eth_get_mac_addr(char *interface_name, unsigned char *mac_addr)
{
  struct ifreq hardware;
  int fd;

  if (interface_name == NULL || mac_addr == NULL) {
    return DDS_RETCODE_BAD_PARAMETER;
  }
  fd = socket(AF_INET, SOCK_DGRAM, 0);
  if (fd < 0) {
    return error_from_errno();
  }
  if (query_interface(fd, interface_name, SIOCGIFHWADDR, &hardware) < 0) {
    dds_return_t result = error_from_errno();
    close(fd);
    return result;
  }
  memcpy(mac_addr, hardware.ifr_hwaddr.sa_data, 6);
  close(fd);
  return DDS_RETCODE_OK;
}
