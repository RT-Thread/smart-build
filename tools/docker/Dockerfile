FROM ubuntu:24.04

ARG USER_NAME=name

RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone
RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list
RUN apt-get update && apt-get install -y sudo locales language-pack-en-base bash bash-completion git curl vim python3 pip tmux bison flex file texinfo \
    && locale-gen en_US.UTF-8 \
    && echo "${USER_NAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && apt-get install -y chrpath cpio diffstat gawk lz4 wget zstd qemu-system-arm \
    && pip install requests scons kconfiglib tqdm --break-system-packages

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

WORKDIR /home/${USER_NAME}
