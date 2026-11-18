<#
.SYNOPSIS
    The Windows dev environment: a Multipass Ubuntu VM with Docker, make and uv, with this checkout
    mounted inside it. Everything else runs there through the Makefile, exactly as on Linux.

.DESCRIPTION
    scripts\dev-vm.ps1                  create the VM if it's missing, start it, mount the repo
    scripts\dev-vm.ps1 make test        run a make target in the VM (any target: dev, e2e, ...)
    scripts\dev-vm.ps1 shell            a shell in the VM, in the repo
    scripts\dev-vm.ps1 stop             stop the VM (its Docker images and volumes are kept)
    scripts\dev-vm.ps1 delete           delete the VM and everything in it

    The VM gets half this PC's logical CPUs (at least 2) and half its memory (4 to 16 GB), and a
    60 GB disk, so builds and the test suite run at full speed. Override with -Cpus, -MemoryGB and
    -DiskGB when creating it. The repo is mounted at /home/ubuntu/draft-bot. make runs there with
    DEV_BIND=0.0.0.0, so the dev stack's ports answer on the VM's address (printed by
    `scripts\dev-vm.ps1`) from this PC's browser; the VM is only reachable from this PC.

    Needs Multipass (https://canonical.com/multipass, `winget install Canonical.Multipass`).
    Multipass's service may need an elevated PowerShell the first time it starts.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "make", "shell", "stop", "delete")]
    [string]$Action = "up",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @(),
    [string]$Name = "draftbot-dev",
    [int]$Cpus = 0,
    [int]$MemoryGB = 0,
    [int]$DiskGB = 60
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Mount = "/home/ubuntu/draft-bot"

function Fail([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command multipass -ErrorAction SilentlyContinue)) {
    Fail "multipass isn't on PATH. Install it: winget install Canonical.Multipass"
}

# Docker from Docker's own apt repository, make, jq and uv (pinned), and the ubuntu user in the
# docker group. Runs once, when the VM is created.
$CloudInit = @'
#cloud-config
package_update: true
packages: [ca-certificates, curl, git, jq, make]
runcmd:
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  - chmod a+r /etc/apt/keyrings/docker.asc
  - echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
  - apt-get update
  - apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  - usermod -aG docker ubuntu
  - su - ubuntu -c "curl -LsSf https://astral.sh/uv/0.13.7/install.sh | sh"
'@

function Get-State {
    $info = multipass info $Name --format json 2>$null
    if ($LASTEXITCODE -ne 0) { return "missing" }
    return ($info | ConvertFrom-Json).info.$Name.state
}

function Invoke-InVm([string]$Command) {
    multipass exec $Name --working-directory $Mount -- env DEV_BIND=0.0.0.0 bash -lc $Command
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Start-Vm {
    $state = Get-State
    if ($state -eq "missing") {
        $logical = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        $totalGB = [math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
        if ($Cpus -le 0) { $Cpus = [math]::Max(2, [math]::Floor($logical / 2)) }
        if ($MemoryGB -le 0) { $MemoryGB = [math]::Min(16, [math]::Max(4, [math]::Floor($totalGB / 2))) }
        Write-Host "Creating $Name: $Cpus CPUs, $MemoryGB GB memory, $DiskGB GB disk (Ubuntu 24.04)."
        $init = New-TemporaryFile
        try {
            Set-Content -Path $init -Value $CloudInit -Encoding ascii
            multipass launch 24.04 --name $Name --cpus $Cpus --memory "${MemoryGB}G" --disk "${DiskGB}G" `
                --cloud-init $init.FullName --timeout 900
            if ($LASTEXITCODE -ne 0) { Fail "multipass launch failed." }
        } finally {
            Remove-Item $init -ErrorAction SilentlyContinue
        }
    } elseif ($state -ne "Running") {
        multipass start $Name
        if ($LASTEXITCODE -ne 0) { Fail "multipass start failed." }
    }
    $mounts = (multipass info $Name --format json | ConvertFrom-Json).info.$Name.mounts
    if (-not ($mounts.PSObject.Properties.Name -contains $Mount)) {
        multipass mount $Repo "${Name}:$Mount"
        if ($LASTEXITCODE -ne 0) { Fail "multipass mount failed." }
    }
}

switch ($Action) {
    "up" {
        Start-Vm
        $ip = (multipass info $Name --format json | ConvertFrom-Json).info.$Name.ipv4[0]
        Write-Host ""
        Write-Host "$Name is running at $ip, with this repo at $Mount."
        Write-Host "  scripts\dev-vm.ps1 make dev     the dev stack: http://${ip}:18080/admin/ and"
        Write-Host "                                  the control panel on http://${ip}:18091"
        Write-Host "  scripts\dev-vm.ps1 make test    the unit suite"
        Write-Host "  scripts\dev-vm.ps1 make         every other target"
        Write-Host "  scripts\dev-vm.ps1 shell        a shell there (export DEV_BIND=0.0.0.0 before make dev)"
    }
    "make" {
        Start-Vm
        Invoke-InVm ("make " + ($Rest -join " "))
    }
    "shell" {
        Start-Vm
        multipass exec $Name --working-directory $Mount -- bash -l
    }
    "stop" { multipass stop $Name }
    "delete" {
        multipass delete --purge $Name
    }
}
