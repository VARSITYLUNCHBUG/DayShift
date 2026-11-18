@echo off
rem From nothing to a running local dev stack: the app against the Discord simulator, seeded with
rem the dev fixtures, plus the control panel. Safe to re-run. See docs\dev\README.md.
rem The cmd.exe twin of scripts/fixture_to_test.sh: same flags, same steps, same output.
setlocal EnableExtensions DisableDelayedExpansion
rem The repo root, taken before `shift` moves %0.
set "ROOT=%~dp0.."

set "FRESH=0"
set "BUILD=1"
set "REAL=0"

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--fresh" (set "FRESH=1" & shift & goto parse)
if /i "%~1"=="--no-build" (set "BUILD=0" & shift & goto parse)
if /i "%~1"=="--real-discord" (set "REAL=1" & shift & goto parse)
if /i "%~1"=="-h" (call :usage & exit /b 0)
if /i "%~1"=="--help" (call :usage & exit /b 0)
1>&2 echo Unknown option: %~1
1>&2 echo.
call :usage 1>&2
exit /b 2
:parsed

cd /d "%ROOT%"
if not defined DRAFTBOT_WAIT_TIMEOUT set "DRAFTBOT_WAIT_TIMEOUT=300"
set "TIMEOUT=%DRAFTBOT_WAIT_TIMEOUT%"
if not defined DRAFTBOT_DEV_PROJECT set "DRAFTBOT_DEV_PROJECT=draftbot-dev"
set "PROJECT=%DRAFTBOT_DEV_PROJECT%"
if not defined DEV_EDGE_PORT set "DEV_EDGE_PORT=18080"
if not defined DEV_WEB_PORT set "DEV_WEB_PORT=18000"
if not defined DEV_SIM_PORT set "DEV_SIM_PORT=18090"
if not defined DEV_PANEL_PORT set "DEV_PANEL_PORT=18091"
if not defined DEV_DB_PORT set "DEV_DB_PORT=15432"
set "DB_PASSWORD_HINT=dev"
if defined DEV_DB_PASSWORD set "DB_PASSWORD_HINT=%DEV_DB_PASSWORD%"
rem The observability overlay, when asked for or already running in this project: without it, a
rem re-run would recreate pgbouncer without the exporter's login.
set "OBS=0"
if "%DRAFTBOT_OBSERVABILITY%"=="1" set "OBS=1"
if "%OBS%"=="1" goto obs_known
for /f %%i in ('docker ps -aq --filter "label=com.docker.compose.project=%PROJECT%" --filter "label=com.docker.compose.service=prometheus" 2^>nul') do set "OBS=1"
if "%OBS%"=="1" echo %PROJECT% runs the observability overlay: keeping it (compose.observability.yaml).
:obs_known
set "FILES=-f compose.yaml -f compose.dev.yaml"
if "%OBS%"=="1" set "FILES=%FILES% -f compose.observability.yaml"
rem docker compose for the dev project. The simulator is behind the `sim` profile. The hint has
rem the same files and profile, so its `stop` stops the simulator too.
set "COMPOSE_HINT=docker compose -p %PROJECT% %FILES% --profile sim"
if "%REAL%"=="1" set "COMPOSE_HINT=docker compose -p %PROJECT% %FILES%"
set "DC=%COMPOSE_HINT%"

call :step Checking Docker
where docker >nul 2>&1 || (call :fail "docker isn't on PATH. Install Docker Desktop or Docker Engine." & exit /b 1)
docker info >nul 2>&1 || (call :fail "Docker isn't running. Start Docker Desktop." & exit /b 1)
docker compose version >nul 2>&1 || (call :fail "The docker compose plugin v2 is missing." & exit /b 1)

if "%REAL%"=="0" goto sim_env
if not exist .env (
    call :fail ".env is missing. Copy .env.example to .env and set DISCORD_TOKEN and DISCORD_GUILD_ID."
    exit /b 1
)
set "DRAFTBOT_ENV_FILE=.env"
echo Real-Discord mode: using .env, no simulator.
goto env_done
:sim_env
if exist .env.dev (
    echo Using .env.dev.
) else (
    copy /y .env.dev.example .env.dev >nul || (call :fail "Couldn't create .env.dev." & exit /b 1)
    echo Created .env.dev from .env.dev.example.
)
set "DRAFTBOT_ENV_FILE=.env.dev"
:env_done

set "BUILD_FLAG=--build"
if "%BUILD%"=="0" set "BUILD_FLAG=--no-build"
set "RUN_BUILD=--build"
if "%BUILD%"=="0" set "RUN_BUILD="

if "%FRESH%"=="0" goto fresh_done
call :step Dropping the dev stack and its database volume (--fresh)
%DC% down -v --remove-orphans
if errorlevel 1 (call :fail "docker compose down failed." & exit /b 1)
:fresh_done

if "%REAL%"=="0" goto start_sim
call :step Starting the database and pgbouncer
%DC% up -d %BUILD_FLAG% --wait --wait-timeout %TIMEOUT% db pgbouncer
if errorlevel 1 (call :explain_failure "The database or pgbouncer didn't become healthy." "db pgbouncer" & exit /b 1)
goto started
:start_sim
call :step Starting the database, pgbouncer and the Discord simulator
%DC% up -d %BUILD_FLAG% --wait --wait-timeout %TIMEOUT% db pgbouncer discord-sim
if errorlevel 1 (call :explain_failure "The database, pgbouncer or the simulator didn't become healthy." "db pgbouncer discord-sim" & exit /b 1)
:started

call :step Migrating and loading presets
%DC% run --rm %RUN_BUILD% migrate
if errorlevel 1 (call :explain_failure "Migrations or load_presets failed." "db" & exit /b 1)

if "%REAL%"=="0" goto seed
echo Skipping the dev seed: fake players don't exist on a real Discord server.
goto seeded
:seed
call :step Seeding the dev fixtures (manage.py dev_seed)
%DC% run --rm --no-deps migrate python manage.py dev_seed
if errorlevel 1 (call :explain_failure "dev_seed failed." "discord-sim" & exit /b 1)
:seeded

call :step Starting web, bot, scheduler, edge and control-panel
%DC% up -d %BUILD_FLAG% --no-deps --wait --wait-timeout %TIMEOUT% web bot scheduler edge control-panel
if errorlevel 1 (call :explain_failure "A service didn't become healthy." "web bot scheduler edge control-panel" & exit /b 1)

if not "%OBS%"=="1" goto obs_done
call :step Starting the observability overlay
%DC% up -d %BUILD_FLAG% --wait --wait-timeout %TIMEOUT%
if errorlevel 1 (call :explain_failure "An observability service didn't become healthy." "prometheus grafana" & exit /b 1)
:obs_done

echo.
echo The dev stack is up.
echo.
echo   Web             http://localhost:%DEV_EDGE_PORT% (through the edge)
echo   Admin           http://localhost:%DEV_EDGE_PORT%/admin/
echo   Control panel   http://localhost:%DEV_PANEL_PORT%
echo   Web, direct     http://localhost:%DEV_WEB_PORT%
echo   Dev control API http://localhost:%DEV_WEB_PORT%/_control/api/
if "%REAL%"=="0" echo   Discord sim     http://localhost:%DEV_SIM_PORT%/_sim/state
echo   Postgres        127.0.0.1:%DEV_DB_PORT% (draftbot / %DB_PASSWORD_HINT%; the app goes through pgbouncer)
echo.
echo Admin login: create a superuser with
echo   %COMPOSE_HINT% exec web python manage.py createsuperuser
echo Logs:  %COMPOSE_HINT% logs -f bot scheduler
echo Stop:  %COMPOSE_HINT% stop      Remove everything: scripts\clean_containers.bat
exit /b 0

:usage
echo Usage: scripts\fixture_to_test.bat [--fresh] [--no-build] [--real-discord]
echo.
echo Builds and starts the draftbot-dev stack, migrates, loads presets, seeds fixtures/dev and prints
echo the URLs. Re-running is safe: it updates what changed and keeps your data.
echo.
echo   --fresh         drop the dev database volume first and start from empty
echo   --no-build      use the images already built instead of rebuilding
echo   --real-discord  skip the simulator and the dev seed; use .env (a real bot token and guild)
echo   -h, --help      show this help
echo.
echo Env: DRAFTBOT_WAIT_TIMEOUT  seconds to wait for each health check (default 300)
echo      DRAFTBOT_DEV_PROJECT   compose project name (default draftbot-dev)
echo      DEV_EDGE_PORT DEV_WEB_PORT DEV_SIM_PORT DEV_PANEL_PORT DEV_DB_PORT
echo      DEV_EDGE_SUBNET DEV_EDGE_IP DEV_EDGE_IP_RANGE
echo                             host ports and the edge network (defaults in compose.dev.yaml),
echo                             to run a second stack beside the first under another project
echo      DEV_DB_PASSWORD        the dev database's password (default dev), set when --fresh
echo      DRAFTBOT_OBSERVABILITY 1 to add compose.observability.yaml (needs DB_MONITOR_PASSWORD);
echo                             on by itself when the project already runs the overlay
exit /b 0

:step
echo.
echo ==^> %*
exit /b 0

:fail
1>&2 echo.
1>&2 echo ERROR: %~1
exit /b 1

rem Shows what state the stack is in and the recent logs of the named services.
:explain_failure
1>&2 echo.
1>&2 echo --- docker compose ps ---
%DC% ps -a 1>&2
1>&2 echo.
1>&2 echo --- last log lines: %~2 ---
%DC% logs --no-color --tail 40 %~2 1>&2
call :fail "%~1"
exit /b 1
