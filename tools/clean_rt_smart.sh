#/bin/bash
bitbake smart-gcc -c cleansstate
bitbake busybox -c cleansstate
bitbake rt-smart -c cleansstate
