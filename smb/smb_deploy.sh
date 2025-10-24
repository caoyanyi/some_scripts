#!/bin/bash

# SMB自动部署与优化脚本
# 功能：一键安装Samba服务、配置共享目录、优化性能参数

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SHARE_PATH="/data/repo"
SAMBA_USER="samba_share"
SAMBA_PASSWD="123456"

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查root权限
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "请使用root权限运行此脚本"
        exit 1
    fi
}

# 安装Samba服务
install_samba() {
    log_info "更新软件包列表..."
    apt-get update
    
    log_info "安装Samba及相关工具..."
    apt-get install -y samba samba-common-bin ntfs-3g
    
    log_info "Samba安装完成"
}

# 创建共享目录和用户
setup_environment() {
    log_info "创建共享目录: $SHARE_PATH"
    mkdir -p $SHARE_PATH
    chmod -R 777 $SHARE_PATH
    
    log_info "创建Samba专用用户..."
    if ! id "$SAMBA_USER" &>/dev/null; then
        useradd -m -s /bin/bash "$SAMBA_USER"
        echo "$SAMBA_USER:$SAMBA_PASSWD" | chpasswd
    fi
    
    log_info "设置Samba用户密码..."
    echo "$SAMBA_PASSWD" | smbpasswd -a -s "$SAMBA_USER"
    
    log_info "环境设置完成"
}

# 优化SMB配置
optimize_smb_config() {
    local config_file="/etc/samba/smb.conf"
    local backup_file="/etc/samba/smb.conf.backup.$(date +%Y%m%d)"
    
    log_info "备份原配置文件..."
    cp "$config_file" "$backup_file"
    
    log_info "生成优化的SMB配置文件..."
    cat > "$config_file" << 'EOF'
[global]
    workgroup = WORKGROUP
    server string = Samba Server
    security = user
    map to guest = bad user
    
    # 性能优化参数
    socket options = TCP_NODELAY SO_RCVBUF=65536 SO_SNDBUF=65536
    read raw = yes
    write raw = yes
    max xmit = 65535
    dead time = 15
    
    # 内存和缓存优化
    getwd cache = yes
    large readwrite = yes
    use sendfile = yes
    aio read size = 1
    aio write size = 1
    
    # 日志设置
    log level = 1
    syslog = 0
    
    # 共享配置
    [Share]
    comment = Shared Folder
    path = $SHARE_PATH
    valid users = $SAMBA_USER
    browseable = yes
    writable = yes
    read only = no
    guest ok = no
    create mask = 0775
    directory mask = 0775
    force user = $SAMBA_USER
    force group = $SAMBA_USER
    
    # 传输优化
    min receivefile size = 16384
    write cache size = 524288
    
EOF
    
    log_info "SMB配置优化完成"
}

# 配置外接硬盘自动挂载
setup_external_drive() {
    local mount_point="$SHARE_PATH"
    local fstab_file="/etc/fstab"
    
    log_warn "请确保外接硬盘已连接，按任意键继续..."
    read -n 1 -s
    
    log_info "检测可用硬盘..."
    lsblk -f
    
    log_warn "请根据上方输出，输入要挂载的设备路径 (如 /dev/sda1):"
    read device_path
    
    if [[ -n "$device_path" && -e "$device_path" ]]; then
        log_info "配置开机自动挂载..."
        echo "$device_path $mount_point ntfs-3g rw,umask=0000,defaults 0 0" >> "$fstab_file"
        
        log_info "立即挂载设备..."
        mount -t ntfs-3g "$device_path" "$mount_point"
        
        log_info "硬盘挂载配置完成"
    else
        log_warn "未检测到有效设备，跳过硬盘挂载配置"
    fi
}

# 防火墙配置
configure_firewall() {
    log_info "配置防火墙规则..."
    
    if command -v ufw &> /dev/null; then
        ufw allow samba
        log_info "UFW防火墙已配置"
    elif command -v iptables &> /dev/null; then
        iptables -A INPUT -p tcp --dport 139 -j ACCEPT
        iptables -A INPUT -p tcp --dport 445 -j ACCEPT
        log_info "iptables已配置"
    fi
}

# 性能监控脚本
setup_monitoring() {
    local monitor_script="/usr/local/bin/smb_monitor.sh"
    
    log_info "创建SMB性能监控脚本..."
    cat > "$monitor_script" << 'EOF'
#!/bin/bash

# SMB服务监控脚本
monitor_smb() {
    echo "=== SMB服务状态监控 ==="
    echo "时间: $(date)"
    echo ""
    
    # 检查服务状态
    if systemctl is-active --quiet smbd; then
        echo "✅ SMB服务运行正常"
    else
        echo "❌ SMB服务未运行"
    fi
    
    # 检查连接数
    local connections=$(smbstatus -b | grep -c "[0-9]")
    echo "当前连接数: $connections"
    
    # 检查网络吞吐量
    echo "网络接口统计:"
    ifconfig | grep -A 5 "eth0\|wlan0"
    
    # 检查磁盘使用情况
    echo ""
    echo "磁盘使用情况:"
    df -h /mnt/samba_share
}

monitor_smb
EOF
    
    chmod +x "$monitor_script"
    log_info "监控脚本已创建: $monitor_script"
}

# 重启服务并验证
restart_and_verify() {
    log_info "重启SMB服务..."
    systemctl restart smbd
    systemctl restart nmbd
    systemctl enable smbd
    systemctl enable nmbd
    
    log_info "验证配置..."
    testparm -s
    
    log_info "检查服务状态..."
    systemctl status smbd --no-pager
    
    log_info "显示当前共享..."
    smbclient -L localhost -U $SAMBA_USER%$SAMBA_PASSWD
}

# 主执行函数
main() {
    log_info "开始SMB服务部署..."
    
    check_root
    install_samba
    setup_environment
    optimize_smb_config
    setup_external_drive
    configure_firewall
    setup_monitoring
    restart_and_verify
    
    log_info "🎉 SMB服务部署完成！"
    echo ""
    echo "访问方式:"
    echo "Windows: \\\\$(hostname -I | awk '{print $1}')\\Share"
    echo "用户名: $SAMBA_USER"
    echo "密码: $SAMBA_PASSWD"
    echo ""
    echo "监控命令: /usr/local/bin/smb_monitor.sh"
    echo "配置文件: /etc/samba/smb.conf"
}

# 执行主函数
main "$@"
