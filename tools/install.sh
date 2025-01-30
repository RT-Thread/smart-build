# !/bin/sh

# 在Linux下准备smart-build的环境
sudo apt update
sudo apt install python3 python3-pip parted unzip dosfstools udevadm -y
pip install scons requests tqdm kconfiglib

sudo add-apt-repository ppa:xmake-io/xmake
sudo apt update
sudo apt install xmake
