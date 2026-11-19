<#
.SYNOPSIS
    The Windows dev environment: a Multipass Ubuntu VM with Docker, make and uv. Everything runs
    there through the Makefile, exactly as on Linux.

.DESCRIPTION
    scripts\dev-vm.ps1                  create the VM if it's missing, start it, copy the repo in
    scripts\dev-vm.ps1 make test        copy the repo in, then run a make target there (any: dev, e2e, ...)
    scripts\dev-vm.ps1 sync             only copy the repo in
    scripts\dev-vm.ps1 shell            a shell in the VM, in its copy of the repo
    scripts\dev-vm.ps1 stop             stop the VM (its Docker images and volumes are kept)
    scripts\dev-vm.ps1 delete           delete the VM and everything in it

    The VM gets half this PC's logical CPUs (at least 2) and half its memory (4 to 16 GB), and a
    60 GB disk, so builds and the test suite run at full speed. Override with -Cpus, -MemoryGB and
    -DiskGB when creating it.

    You edit and commit here, on Windows. Before each command the VM's copy at
    /home/ubuntu/draft-bot is brought in line with this checkout: every file Git tracks or would
    track, plus .env, .env.dev and your deploy inventories, which Git ignores. It lives on the VM's
    own disk, so builds and tests run at native speed and no host folder is shared with the VM. Its
    caches (.venv and the like) are kept between runs. make runs there with DEV_BIND=0.0.0.0, so
    the dev stack's ports answer on the VM's address (printed by `scripts\dev-vm.ps1`), which only
    this PC can reach.

    Needs Multipass (https://canonical.com/multipass, `winget install Canonical.Multipass`).
    Multipass's service may need an elevated PowerShell the first time it starts.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "make", "sync", "shell", "stop", "delete")]
    [string]$Action = "up",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @(),
    [string]$Name = "draftbot-dev",
    [int]$Cpus = 0,
    [int]$MemoryGB = 0,
    [int]$DiskGB = 60
)

# Not "Stop": Windows PowerShell 5.1 turns anything a native command writes to stderr into a
# terminating error, even redirected, and multipass reports a missing VM that way. Every native
# call below checks $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Copy = "/home/ubuntu/draft-bot"

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

# Run in the VM after the archive lands: unpack it over the copy, remove what is no longer in the
# checkout (but never the caches and local files listed here), and give the copy a Git index of
# its own, which pre-commit needs. Commits belong in the Windows checkout, not in this one.
$Unpack = @'
set -eu
copy=/home/ubuntu/draft-bot
mkdir -p "$copy"
tar -xf /home/ubuntu/draftbot-sync.tar -C "$copy"
tar -tf /home/ubuntu/draftbot-sync.tar | sed 's#^\./##' | sort > /tmp/draftbot-sync.list
cd "$copy"
find . -type f \
    -not -path './.venv/*' -not -path './.git/*' -not -path './test-results/*' \
    -not -path './.pytest_cache/*' -not -path './.hypothesis/*' -not -path './.mypy_cache/*' \
    -not -path './.ruff_cache/*' -not -path './staticfiles/*' -not -path '*/node_modules/*' \
    -not -path './deploy/ansible/.venv/*' -not -path './deploy/ansible/collections/*' \
    -not -path './deploy/ansible/backups/*' -not -path './services/discord-sim/.venv/*' \
    -not -name '.env.dev' \
    | sed 's#^\./##' | sort | comm -23 - /tmp/draftbot-sync.list | xargs -r -d '\n' rm -f
[ -d .git ] || git init -q
git add -A
rm -f /home/ubuntu/draftbot-sync.tar
'@

function Get-State {
    $info = multipass info $Name --format json 2>$null
    if ($LASTEXITCODE -ne 0) { return "missing" }
    return ($info | ConvertFrom-Json).info.$Name.state
}

function Sync-Repo {
    Push-Location $Repo
    try {
        $files = @(git -c core.safecrlf=false ls-files --cached --others --exclude-standard 2>$null)
        if ($LASTEXITCODE -ne 0) { Fail "git ls-files failed: is this a Git checkout?" }
        $extra = @(".env", ".env.dev") + @(
            Get-ChildItem -Recurse -File deploy\ansible\inventories -ErrorAction SilentlyContinue |
                ForEach-Object { Resolve-Path -Relative $_.FullName }
        )
        $files = @($files + $extra) |
            ForEach-Object { $_ -replace '^\.\\', '' -replace '\\', '/' } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Sort-Object -Unique
        $temp = [IO.Path]::GetTempPath()
        $list = Join-Path $temp "draftbot-sync.list"
        [IO.File]::WriteAllLines($list, [string[]]$files)
        tar.exe -cf (Join-Path $temp "draftbot-sync.tar") -T $list
        if ($LASTEXITCODE -ne 0) { Fail "tar failed." }
    } finally {
        Pop-Location
    }
    # multipass transfer reads a Windows path such as C:\... as a VM called C, so it gets a
    # relative name from inside the temp folder.
    Push-Location $temp
    try {
        multipass transfer draftbot-sync.tar "${Name}:/home/ubuntu/draftbot-sync.tar"
        if ($LASTEXITCODE -ne 0) { Fail "multipass transfer failed." }
    } finally {
        Remove-Item draftbot-sync.tar, draftbot-sync.list -ErrorAction SilentlyContinue
        Pop-Location
    }
    multipass exec $Name -- bash -c ($Unpack -replace "`r", "")
    if ($LASTEXITCODE -ne 0) { Fail "Unpacking the repo in the VM failed." }
    Write-Host "Synced $($files.Count) files to ${Name}:$Copy."
}

function Start-Vm {
    $state = Get-State
    if ($state -eq "missing") {
        $logical = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        $totalGB = [math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
        if ($Cpus -le 0) { $Cpus = [math]::Max(2, [math]::Floor($logical / 2)) }
        if ($MemoryGB -le 0) { $MemoryGB = [math]::Min(16, [math]::Max(4, [math]::Floor($totalGB / 2))) }
        Write-Host "Creating ${Name}: $Cpus CPUs, $MemoryGB GB memory, $DiskGB GB disk (Ubuntu 24.04)."
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
}

switch ($Action) {
    "up" {
        Start-Vm
        Sync-Repo
        $ip = (multipass info $Name --format json | ConvertFrom-Json).info.$Name.ipv4[0]
        Write-Host ""
        Write-Host "$Name is running at $ip, with a copy of this repo at $Copy."
        Write-Host "  scripts\dev-vm.ps1 make dev     the dev stack: http://${ip}:18080/admin/ and"
        Write-Host "                                  the control panel on http://${ip}:18091"
        Write-Host "  scripts\dev-vm.ps1 make test    the unit suite"
        Write-Host "  scripts\dev-vm.ps1 make         every other target"
        Write-Host "  scripts\dev-vm.ps1 shell        a shell there (run sync first after editing here)"
    }
    "make" {
        Start-Vm
        Sync-Repo
        multipass exec $Name --working-directory $Copy -- env DEV_BIND=0.0.0.0 bash -lc ("make " + ($Rest -join " "))
        exit $LASTEXITCODE
    }
    "sync" {
        Start-Vm
        Sync-Repo
    }
    "shell" {
        Start-Vm
        multipass exec $Name --working-directory $Copy -- env DEV_BIND=0.0.0.0 bash -l
    }
    "stop" { multipass stop $Name }
    "delete" {
        multipass delete --purge $Name
    }
}
