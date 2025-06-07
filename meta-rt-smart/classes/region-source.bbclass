# Set default value for REGION if not defined
REGION ?= "AUTO"

def determine_region(d):
    region = d.getVar('REGION')
    if region != "AUTO":
        return region

    # Auto detect
    import socket, requests
    try:
        ip = requests.get('https://icanhazip.com').text.strip()
        cstr = "http://ip-api.com/json/" + ip + "?fields=countryCode"
        response = requests.get(cstr).text.strip()
        detected_region = "CN" if len(response.split('"CN"')) > 1 else "GLOBAL"
        
        # Update REGION variable with the detected value
        d.setVar('REGION', detected_region)
        
        if detected_region == "CN":
            bb.plain("****** Using gitee source (auto-detected)")
        else:
            bb.plain("****** Using github source (auto-detected)")
        return detected_region
    except:
        bb.plain("****** Default: using github source (detection failed)")
        d.setVar('REGION', "GLOBAL")
        return "GLOBAL"

def set_preferred_source(d):
    region = determine_region(d)
    if region == "CN":
        d.setVar('SRC_URI', d.getVar('SRC_URI_GITEE'))
    else:
        d.setVar('SRC_URI', d.getVar('SRC_URI_GITHUB'))
