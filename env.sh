#!/bin/bash

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export XMAKE_RCFILES=${script_dir}/tools/scripts/xmake.lua
export RT_XMAKE_LINK_TYPE="static"

# Check whether unzip is installed.
if ! command -v unzip &> /dev/null; then
    echo "Unzip is not installed. Installing unzip"

    # Automatically install unzip according to package manager
    if [[ -n $(command -v apt-get) ]]; then
        sudo apt-get update
        sudo apt-get install -y unzip
    elif [[ -n $(command -v yum) ]]; then
        sudo yum install -y unzip
    elif [[ -n $(command -v dnf) ]]; then
        sudo dnf install -y unzip
    elif [[ -n $(command -v pacman) ]]; then
        sudo pacman -Sy --noconfirm unzip
    else
        echo "Unrecognized package manager, please install unzip manually."
        exit 1
    fi

    echo "Unzip has been successfully installed."
    echo "smart-build env ready!"
else
    echo "smart-build env ready!"
fi

export PATH=`python3 -m site --user-base`/bin:$HOME/.env/tools/scripts:$PATH
export RTT_EXEC_PATH=/usr/bin
