# Source mirror policy. Set REGION = "GLOBAL" in local.conf to use upstream
# GitHub/official sources instead of China mirrors.
REGION ?= "CN"

def set_preferred_source(d):
    region = d.getVar('REGION') or "CN"
    if region == "CN":
        src_uri = d.getVar('SRC_URI_CN') or d.getVar('SRC_URI_GITEE') or d.getVar('SRC_URI_GITHUB')
    elif region == "GLOBAL":
        src_uri = d.getVar('SRC_URI_GITHUB') or d.getVar('SRC_URI_GITEE') or d.getVar('SRC_URI_CN')
    else:
        bb.fatal('Unsupported REGION "%s"; use "CN" or "GLOBAL".' % region)

    if not src_uri:
        bb.fatal("No source URI is defined for REGION=%s" % region)

    d.setVar('SRC_URI', src_uri)
