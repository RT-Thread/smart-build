inherit region-source

DESCRIPTION = "RT-Thread Smart Environment Setup"
LICENSE = "CLOSED"

SRC_URI_GITEE = "git://gitee.com/RT-Thread-Mirror/env.git;branch=master;protocol=https;name=env \
                 git://gitee.com/RT-Thread-Mirror/packages.git;branch=master;protocol=https;name=packages \
                 git://gitee.com/RT-Thread-Mirror/sdk.git;branch=main;protocol=https;name=sdk \
"

SRC_URI_GITHUB = "git://github.com/RT-Thread/env.git;branch=master;protocol=https;name=env \
                  git://github.com/RT-Thread/packages.git;branch=master;protocol=https;name=packages \
                  git://github.com/RT-Thread/sdk.git;branch=main;protocol=https;name=sdk \
"

python () {
    set_preferred_source(d)
}

SRCREV_env = "AUTOINC"
SRCREV_packages = "AUTOINC"
SRCREV_sdk = "AUTOINC"

SRCREV_FORMAT = "env_packages_sdk"

S = "${WORKDIR}/git"

do_install_env() {
    bbplain "****** Installing RT-Thread environment"
    
    mkdir -p ~/.env/local_pkgs ~/.env/packages ~/.env/tools
    
    cp -r ${WORKDIR}/sources-unpack/env ~/.env/tools/scripts
    cp ${WORKDIR}/sources-unpack/env/env.sh ~/.env/
    cp ${WORKDIR}/sources-unpack/env/Kconfig ~/.env/tools/
    cp -r ${WORKDIR}/sources-unpack/packages ~/.env/packages/
    cp -r ${WORKDIR}/sources-unpack/sdk ~/.env/packages/
    echo "source \"\$PKGS_DIR/packages/Kconfig\"" > ~/.env/packages/Kconfig
}

addtask do_install_env after do_unpack 