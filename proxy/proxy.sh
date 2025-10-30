#!/bin/bash

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

LISTEN_IP=10.8.0.1
BACKEND_IP=10.8.0.0
HTTP_PORT=3129
SOCKET_PORT=3127

apt update
apt install -y ufw

# 安装http代理
echo "正在安装http代理……"
apt install -y tinyproxy

sed -i "s/Port \d\+/Port ${HTTP_PORT}/" /etc/tinyproxy/tinyproxy.conf
sed -i "s/Listen \w\+/Listen ${LISTEN_IP}/" /etc/tinyproxy/tinyproxy.conf
sed -i "s/Allow \w\+/Allow ${BACKEND_IP}/" /etc/tinyproxy/tinyproxy.conf
sed -i "s/#DisableViaHeader \w\+/DisableViaHeader Yes/" /etc/tinyproxy/tinyproxy.conf

systemctl restart tinyproxy
systemctl enable tinyproxy

ufw allow ${HTTP_PORT}

# 安装socket代理
echo "正在安装socket代理……"
apt install -y dante-server

cat > /etc/danted.conf << EOF
logoutput: syslog
internal: ${LISTEN_IP} port = ${SOCKET_PORT}
external: eth0  # 替换为你的网卡名称，可用 `ip a` 查看
method: none
user.notprivileged: nobody

client pass {
    from: ${BACKEND_IP}/24 to: 0.0.0.0/0
    log: connect
}

pass {
    from: ${BACKEND_IP}/24 to: 0.0.0.0/0
    protocol: tcp udp
    log: connect
}
EOF

systemctl restart danted
systemctl enable danted

ufw allow ${SOCKET_PORT}

echo "http://${LISTEN_IP}:${HTTP_PORT}"
echo "socket://${LISTEN_IP}:${SOCKET_PORT}"
