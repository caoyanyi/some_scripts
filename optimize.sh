#!/bin/bash
echo '一些小优化...'

dpkg-reconfigure unattended-upgrades

# 优化Swap空间使用
swapoff -a
dd if=/dev/zero of=/swapfile bs=64M count=16
mkswap /swapfile
swapon -a

# 优化网络参数，调整Swappiness值
sysctl vm.swappiness=10
cat >> /etc/sysctl.conf <<EOF
vm.swappiness=10
vm.vfs_cache_pressure=50
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backoff = 0
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_rfc1337 = 0
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_base_mss = 10240
net.ipv4.tcp_max_mss = 16384
EOF

# 调整系统资源限制
cat >> /etc/security/limits.conf <<EOF
* soft nofile 65535
* hard nofile 65535
* soft nproc 65535
* hard nproc 65535
EOF

# TLP是一款很好的电源管理工具，可以自动调节电源参数以减少功耗，从而提高系统运行速度
add-apt-repository ppa:linrunner/tlp -y
apt update -y -qq
apt install tlp tlp-rdw -y -qq
tlp start
systemctl mask grub-initrd-fallback.service

# 开机启动加速
sed -i '/\[Service\]/a \TimeoutStartSec=2sec' /lib/systemd/system/systemd-networkd-wait-online.service

# 关闭图形化界面
systemctl set-default multi-user.target

# 屏蔽PCI错误，禁用IPV6
sed -i '/^GRUB_CMDLINE_LINUX_DEFAULT/cGRUB_CMDLINE_LINUX_DEFAULT="quiet zswap.enabled=1 pci=noaer pcie_aspm=off pcie_ptm=off ipv6.disable=1 intel_idle.max_cstate=1 i915.enable_dc=0"' /etc/default/grub
update-grub

# Preload 是一个后台运行的守护进程，它分析用户行为和频繁运行的应用，让你更快打开常用的软件。
apt install -y -qq preload

apt autoremove -y
apt autoclean -y

# 优化固态硬盘
apt install util-linux -y -qq
systemctl enable fstrim.timer
systemctl start fstrim.timer

# 关闭休眠
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'

# 设置系统时区为上海
echo '正在设置系统时区...'
ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
dpkg-reconfigure -f noninteractive tzdata

# 设置sudo免密
sed -i "s/ALL=(ALL\(:ALL\)\?) ALL/ALL=(ALL:ALL) NOPASSWD:ALL/g" /etc/sudoers

# 使用root账号可以设置inotify监听大小
echo 8192000 > /proc/sys/fs/inotify/max_user_watches

# 优化无线网络
echo "options iwlwifi power_save=0" >> /etc/modprobe.d/iwlwifi.conf
echo "options iwlmvm power_scheme=1" >> /etc/modprobe.d/iwlwifi.conf

sed -i 's/^wifi.powersave/cwifi.powersave = 2/' /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf
