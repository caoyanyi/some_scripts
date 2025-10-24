#!/bin/bash

# SMB性能调优脚本
# 用于进一步优化已部署的SMB服务

set -e

# 网络优化
optimize_network() {
    echo "优化网络参数..."
    
    # 提高网络缓冲区大小
    echo 'net.core.rmem_max = 16777216' >> /etc/sysctl.conf
    echo 'net.core.wmem_max = 16777216' >> /etc/sysctl.conf
    echo 'net.ipv4.tcp_rmem = 4096 87380 16777216' >> /etc/sysctl.conf
    echo 'net.ipv4.tcp_wmem = 4096 16384 16777216' >> /etc/sysctl.conf
    
    sysctl -p
}

# 磁盘I/O优化
optimize_disk_io() {
    echo "优化磁盘I/O..."
    
    # 如果有外接硬盘，调整调度器
    local external_drive=$(lsblk -l -o NAME,MOUNTPOINT | grep "/mnt/samba_share" | awk '{print $1}')
    
    if [[ -n "$external_drive" ]]; then
        echo "正在优化外接硬盘性能..."
        echo noop > /sys/block/${external_drive%?}/queue/scheduler 2>/dev/null || true
    fi
}

# 内存优化
optimize_memory() {
    echo "优化内存使用..."
    
    # 增加文件缓存参数
    echo 'vm.dirty_background_ratio = 5' >> /etc/sysctl.conf
    echo 'vm.dirty_ratio = 10' >> /etc/sysctl.conf
}

# 生成性能测试脚本
create_benchmark_script() {
    local bench_script="/usr/local/bin/smb_benchmark.sh"
    
    cat > "$bench_script" << 'EOF'
#!/bin/bash

benchmark_smb() {
    local test_file="/mnt/samba_share/test_benchmark.bin"
    local size_mb=100
    
    echo "开始SMB性能测试..."
    echo "测试文件大小: ${size_mb}MB"
    echo ""
    
    # 写入测试
    echo "写入性能测试..."
    time (dd if=/dev/zero of="$test_file" bs=1M count=$size_mb 2>/dev/null)
    
    # 读取测试
    echo ""
    echo "读取性能测试..."
    time (dd if="$test_file" of=/dev/null bs=1M 2>/dev/null)
    
    # 清理测试文件
    rm -f "$test_file"
    
    echo "测试完成"
}

benchmark_smb
EOF
    
    chmod +x "$bench_script"
    echo "性能测试脚本已创建: $bench_script"
}

main() {
    echo "开始SMB性能调优..."
    
    optimize_network
    optimize_disk_io
    optimize_memory
    create_benchmark_script
    
    echo "🎯 性能调优完成！"
    echo "运行性能测试: /usr/local/bin/smb_benchmark.sh"
}

main "$@"
