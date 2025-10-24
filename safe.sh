# !/bin/bash

# 设置shell连接超时，等保要求不大于600
read -p "请输入shell连接超时时间,等保要求不大于600（默认300）：" timeout
timeout=${timeout:-300}
if [ "$timeout" -gt 600 ]; then
    timeout=600
fi
echo "timeout=$timeout" >> /etc/profile

# 移除重要文件的suid和sgid权限
chmod u-s /usr/bin/gpasswd /usr/bin/chfn /usr/bin/chsh /usr/bin/newgrp /bin/mount /bin/umount
chmod g-s /usr/bin/chage 

# 安全套接字加密远程管理ssh
echo 'Protocol 2' >> /etc/ssh/sshd_config
# SSH空闲超时时间
read -p "请输入SSH空闲超时时间（默认600）：" idle_timeout
idle_timeout=${idle_timeout:-600}
echo "ClientAliveInterval=$idle_timeout" >> /etc/ssh/sshd_config
# SSH登录超时配置
read -p "请输入SSH登录超时时间（默认60）：" login_timeout
login_timeout=${login_timeout:-60}
echo "LoginGraceTime=$login_timeout" >> /etc/ssh/sshd_config
systemctl restart sshd

# 开启TCP-SYNcookie保护
read -p "是否开启TCP-SYNcookie保护（默认开启）：" enable
enable=${enable:-yes}
if [ "$enable" = "yes" ]; then
    echo 'net.ipv4.tcp_syncookies=1' >> /etc/sysctl.conf
    sysctl -p
fi

# 对grub配置安全的权限
if [ -d /boot/grub2 ]; then
    chmod 600 /boot/grub2/grub.cfg && chown root /boot/grub2/grub.cfg
fi
if [ -d /boot/grub ]; then
    chmod 600 /boot/grub/grub.cfg && chown root /boot/grub/grub.cfg
fi

# SSH密码检查
read -p "是否开启SSH密码检查（默认开启）：" enable
enable=${enable:-yes}
if [ "$enable" = "yes" ]; then
    # 长度限制
    read -p "请输入SSH密码长度限制（默认9）：" minlen
    minlen=${minlen:-9}
    echo "minlen=$minlen" >> /etc/security/pwquality.conf

    # 密码复杂度要求，至少包含小写字母、大写字母、数字、特殊字符等中的几种
    read -p "请输入SSH密码复杂度要求（默认4）：" minclass
    minclass=${minclass:-4}
    echo "minclass=$minclass" >> /etc/security/pwquality.conf
fi

# 禁用telnet服务（不安全的远程登录服务）
if systemctl list-units --all --type=service | grep -q telnet; then
    systemctl stop telnet
    systemctl disable telnet
fi

# 限制root用户远程登录
read -p "是否限制root用户远程登录（默认不限制）：" limit_root
limit_root=${limit_root:-no}
if [ "$limit_root" = "yes" ]; then
    echo 'PermitRootLogin no' >> /etc/ssh/sshd_config
fi

# 配置SSH密钥认证
echo 'PubkeyAuthentication yes' >> /etc/ssh/sshd_config
read -p "是否开启密码认证（默认不开启）：" enable
enable=${enable:-no}
if [ "$enable" = "yes" ]; then
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
fi

# 配置账户自动锁定策略
echo "FAIL_DELAY=4" >> /etc/login.defs  # 登录失败后延迟4秒重试
echo "FAILLOG_ENAB=YES" >> /etc/login.defs  # 启用登录失败记录
read -p "是否开启账户密码自动锁定策略（默认开启）：" enable
enable=${enable:-yes}
if [ "$enable" = "yes" ]; then
    chage --mindays 7 root
    sed -i "s/^PASS_MIN_DAYS.*/PASS_MIN_DAYS 7/" /etc/login.defs # 密码修改最小间隔7天
    echo "PASS_MAX_DAYS 90" >> /etc/login.defs  # 密码最大有效期90天
    echo "PASS_WARN_AGE 7" >> /etc/login.defs  # 密码过期前7天警告
fi

# 开启审计日志
if command -v auditctl > /dev/null; then
    auditctl -w /etc/passwd -p wa -k passwd_changes
    auditctl -w /etc/shadow -p wa -k shadow_changes
fi

# 防止IP欺骗
echo 'net.ipv4.conf.all.rp_filter=1' >> /etc/sysctl.conf
echo 'net.ipv4.conf.default.rp_filter=1' >> /etc/sysctl.conf
sysctl -p

# 隐藏系统信息
if [ -d /etc/apache2 ]; then
    echo 'ServerTokens Prod' >> /etc/apache2/conf-available/security.conf  # 若有Apache服务
    echo 'ServerSignature Off' >> /etc/apache2/conf-available/security.conf  # 若有Apache服务
fi
