<# 
WSL 端口转发管理脚本
作者：ChatGPT
功能：
 - 交互式菜单
 - 单端口/批量添加与删除
 - 清空所有转发规则
 - 查看WSL状态与系统信息
 - 管理员权限检测
 - 输入验证与实时反馈
#>

# 检查管理员权限
function Check-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Warning "请以管理员身份运行此脚本！"
        Pause
        exit
    }
}

# 获取当前WSL的 IP 地址
function Get-WSLIP {
    try {
        $ip = wsl hostname -I | ForEach-Object { $_.Trim().Split()[0] }
        if (-not $ip) {
            Write-Host "无法获取 WSL IP，请确认 WSL 已启动。" -ForegroundColor Red
        }
        return $ip
    } catch {
        Write-Host "获取 WSL IP 失败：$_" -ForegroundColor Red
        return $null
    }
}

# 添加端口转发规则
function Add-Port {
    param([int[]]$Ports)
    $ip = Get-WSLIP
    if (-not $ip) { return }
    foreach ($port in $Ports) {
        if ($port -lt 1 -or $port -gt 65535) {
            Write-Host "端口 $port 无效（1~65535）。" -ForegroundColor Yellow
            continue
        }
        Write-Host "正在添加端口转发规则：$port → $ip" -ForegroundColor Cyan
        try {
            netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$ip connectport=$port
            Write-Host "端口 $port 添加成功。" -ForegroundColor Green
        } catch {
            Write-Host "添加端口 $port 失败：$_" -ForegroundColor Red
        }
    }
}

# 删除端口转发规则
function Remove-Port {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        Write-Host "正在删除端口转发规则：$port" -ForegroundColor Cyan
        try {
            netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0
            Write-Host "端口 $port 删除成功。" -ForegroundColor Green
        } catch {
            Write-Host "删除端口 $port 失败：$_" -ForegroundColor Red
        }
    }
}

# 清空所有端口转发规则
function Clear-All {
    Write-Host "确认清空所有端口转发规则？（Y/N）" -ForegroundColor Yellow
    $confirm = Read-Host
    if ($confirm -match '^[Yy]$') {
        try {
            netsh interface portproxy reset
            Write-Host "所有规则已清空。" -ForegroundColor Green
        } catch {
            Write-Host "清空失败：$_" -ForegroundColor Red
        }
    } else {
        Write-Host "操作已取消。" -ForegroundColor Yellow
    }
}

# 显示当前端口转发列表
function Show-List {
    Write-Host "当前端口转发规则：" -ForegroundColor Cyan
    netsh interface portproxy show all
}

# 显示WSL状态信息
function Show-WSLInfo {
    Write-Host "`nWSL 系统信息：" -ForegroundColor Cyan
    try {
        $ip = Get-WSLIP
        Write-Host "WSL IP 地址： $ip"
        Write-Host "WSL 发行版："
        wsl -l -v
        Write-Host "`nWSL 版本："
        wsl --version
    } catch {
        Write-Host "无法获取 WSL 信息：$_" -ForegroundColor Red
    }
}

# 主菜单
function Main-Menu {
    while ($true) {
        Write-Host "`n==================== WSL 端口转发管理 ====================" -ForegroundColor Cyan
        Write-Host "1. 添加单个端口转发"
        Write-Host "2. 批量添加端口转发"
        Write-Host "3. 删除端口转发"
        Write-Host "4. 批量删除端口转发"
        Write-Host "5. 清空所有端口转发规则"
        Write-Host "6. 查看 WSL 状态与端口列表"
        Write-Host "0. 退出"
        Write-Host "=========================================================="
        $choice = Read-Host "请选择操作 [0-6]"

        switch ($choice) {
            '1' {
                $port = Read-Host "请输入端口号"
                if ($port -match '^\d+$') { Add-Port @([int]$port) } else { Write-Host "输入无效" -ForegroundColor Yellow }
            }
            '2' {
                $ports = Read-Host "请输入多个端口（用逗号或空格分隔）"
                $portsArray = $ports -split '[, ]+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }
                Add-Port $portsArray
            }
            '3' {
                $port = Read-Host "请输入要删除的端口号"
                if ($port -match '^\d+$') { Remove-Port @([int]$port) } else { Write-Host "输入无效" -ForegroundColor Yellow }
            }
            '4' {
                $ports = Read-Host "请输入多个要删除的端口（用逗号或空格分隔）"
                $portsArray = $ports -split '[, ]+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }
                Remove-Port $portsArray
            }
            '5' { Clear-All }
            '6' { Show-WSLInfo; Show-List }
            '0' { Write-Host "退出脚本。" -ForegroundColor Yellow; break }
            default { Write-Host "请输入 0-6 之间的数字。" -ForegroundColor Yellow }
        }
    }
}

# 主程序入口
Check-Admin
Main-Menu
