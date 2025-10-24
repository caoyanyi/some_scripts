#!/bin/bash

# 设置默认值
VERSION="0.61.1"
PORT="7100"
CUSTOM_PORT="8800"
PRIVILEGE_KEY=""
WEB_PORT="7600"
WEB_USER="admin"
WEB_PASS=""

# 检查必要的命令
if ! command -v wget &>/dev/null && ! command -v curl &>/dev/null; then
    echo "错误：需要安装wget或curl才能继续"
    exit 1
fi

# 函数：显示帮助信息
show_help() {
    echo "使用方法："
    echo "  $0 [-v 版本号] [-p 监听端口] [-c 自定义端口] [-k 密钥] [-w web端口] [-u 用户名] [-x 密码]"
    echo ""
    echo "参数说明："
    echo "  -v 版本号      FRP版本号（默认：$VERSION）"
    echo "  -p 监听端口     FRPS监听端口（默认：$PORT）"
    echo "  -c 自定义端口   自定义端口号（默认：$CUSTOM_PORT）"
    echo "  -k 密钥        连接密钥（必填）"
    echo "  -w web端口     web后台端口（默认：$WEB_PORT）"
    echo "  -u 用户名      web后台用户名（默认：admin）"
    echo "  -x 密码        web后台密码（选填，如不指定则使用连接密钥）"
    echo "  -remove        卸载FRP"
}

# 解析参数
while getopts ":v:p:c:k:w:u:x:h:remove" opt; do
    case $opt in
        v) VERSION="$OPTARG";;
        p) PORT="$OPTARG";;
        c) CUSTOM_PORT="$OPTARG";;
        k) PRIVILEGE_KEY="$OPTARG";;
        w) WEB_PORT="$OPTARG";;
        u) WEB_USER="$OPTARG";;
        x) WEB_PASS="$OPTARG";;
        remove) uninstall_frps; exit 0;;
        h|\?) show_help; exit 0;;
    esac
done

# 检查必填参数
if [ -z "$PRIVILEGE_KEY" ]; then
    echo "错误：连接密钥是必填参数！"
    exit 1
fi

# 如果没有指定密码，则使用连接密钥作为密码
if [ -z "$WEB_PASS" ]; then
    WEB_PASS="$PRIVILEGE_KEY"
fi

# 函数：下载FRP
download_frps() {
    local url="https://ghfast.top/https://github.com/fatedier/frp/releases/download/v$VERSION/frp_${VERSION}_linux_amd64.tar.gz"

    echo "正在下载FRPS..."

    if [ -f /tmp/frp.tar.gz ]; then
        return
    fi

    if command -v wget &>/dev/null; then
        wget -q -O /tmp/frp.tar.gz "$url"
    else
        curl -o /tmp/frp.tar.gz  -sSL "$url"
    fi

    if [ $? -ne 0 ]; then
        echo "下载失败，请检查网络连接和版本号是否正确"
        exit 1
    fi
}

# 函数：配置FRPS
configure_frps() {
    cat > /etc/frp/frps.toml << EOF
[common]
bindAddr = "0.0.0.0"
bindPort = ${PORT}
vhostHTTPPort = ${CUSTOM_PORT}

auth.method = "token"
auth.token = "${PRIVILEGE_KEY}"  # 这个是可以理解成连接密码，自己写自己的

# web面板
webServer.addr = "0.0.0.0"
webServer.port = ${WEB_PORT}  # frp后台端口
webServer.user = "${WEB_USER}" # frp后台账号
webServer.password = "${WEB_PASS}" # frp后台密码
EOF
}

# 函数：创建systemd服务文件
create_systemd_service() {
    cat > /etc/systemd/system/frps.service << EOF
[Unit]
Description=Frp Server Service
After=network.target

[Service]
Type=simple
DynamicUser=yes
Restart=on-failure
RestartSec=5s
ExecStart=/usr/bin/frps -c /etc/frp/frps.toml
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF
}

# 卸载函数
uninstall_frps() {
    echo "开始卸载FRPS..."

    # 停止服务
    if command -v systemctl &>/dev/null; then
        echo "停止FRPS服务..."
        systemctl stop frps
        systemctl disable frps
        rm -f /etc/systemd/system/frps.service
        systemctl daemon-reload
    else
        echo "停止FRPS服务..."
        /etc/init.d/frps stop
        update-rc.d -f frps remove
    fi

    # 删除二进制文件
    echo "删除FRPS二进制文件..."
    rm -f /usr/bin/frps

    # 删除配置文件
    echo "删除配置文件..."
    rm -rf /etc/frp

    # 删除系统服务文件
    echo "删除系统服务文件..."
    if [ -f "/etc/init.d/frps" ]; then
        rm -f /etc/init.d/frps
    fi

    echo "卸载完成！"
}

# 主安装流程
echo "开始安装FRPS..."

# 创建必要的目录
mkdir -p /etc/frp

# 下载和解压FRP
download_frps
tar -zxvf /tmp/frp.tar.gz -C /tmp

# 复制二进制文件到系统路径
cp "/tmp/frp_${VERSION}_linux_amd64/frps" /usr/bin/

# 配置FRPS
configure_frps

# 创建并启用systemd服务
create_systemd_service
systemctl daemon-reload
systemctl enable frps
systemctl start frps

# 显示安装结果
echo ""
echo "安装完成！"
echo "FRPS将在系统启动时自动运行。"
echo "当前配置："
echo "版本号：$VERSION"
echo "监听端口：$PORT"
echo "自定义端口：$CUSTOM_PORT"
echo "Web管理端口：$WEB_PORT"
echo "Web用户名：$WEB_USER"

# 检查服务状态
systemctl status frps
