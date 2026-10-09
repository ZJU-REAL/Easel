# PSScriptAnalyzer 配置（CI 的 lint-installers job 使用）
@{
    Severity     = @('Error', 'Warning')
    ExcludeRules = @(
        # setup.ps1 / gateway.ps1 是面向用户的安装与运维脚本，终端输出就是它们的产出物，
        # Write-Host 正是此处该用的东西（Write-Output 会污染函数返回值 —— PowerShell 里
        # 函数会把所有未捕获的输出一并作为返回值，这在本仓库是真实踩过的坑）。
        'PSAvoidUsingWriteHost',
        # 安装脚本里的 Set-* 函数不需要 -WhatIf/-Confirm：它本身就是一次性的交互式
        # 安装动作，整个脚本的「预演」能力由 EASEL_SETUP_MODE=check 提供，而不是靠
        # 每个函数各自实现 ShouldProcess。
        'PSUseShouldProcessForStateChangingFunctions'
    )
}
