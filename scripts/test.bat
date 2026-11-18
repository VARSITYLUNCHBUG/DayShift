@echo off
rem Runs the test suites in throwaway stacks and exits with their result. See docs\dev\README.md.
rem The cmd.exe twin of scripts/test.sh: same modes, flags and output.
setlocal EnableExtensions DisableDelayedExpansion
rem The repo root, taken before `shift` moves %0.
set "ROOT=%~dp0.."

set "MODE=unit"
set "LOCAL=0"
set "BUILD=1"
set "PYARGS="

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="unit" (set "MODE=unit" & shift & goto parse)
if /i "%~1"=="e2e" (set "MODE=e2e" & shift & goto parse)
if /i "%~1"=="all" (set "MODE=all" & shift & goto parse)
if /i "%~1"=="--local" (set "LOCAL=1" & shift & goto parse)
if /i "%~1"=="--no-build" (set "BUILD=0" & shift & goto parse)
if /i "%~1"=="-h" (call :usage & exit /b 0)
if /i "%~1"=="--help" (call :usage & exit /b 0)
if "%~1"=="--" (shift & goto pyargs)
1>&2 echo Unknown argument: %~1
1>&2 echo.
call :usage 1>&2
exit /b 2
rem Everything after -- goes to pytest, quotes kept.
:pyargs
if "%~1"=="" goto parsed
set "PYARGS=%PYARGS% %1"
shift
goto pyargs
:parsed

if "%LOCAL%%MODE%"=="1e2e" (
    1>&2 echo ERROR: --local only applies to the unit suite.
    exit /b 2
)

cd /d "%ROOT%"
if not defined DRAFTBOT_WAIT_TIMEOUT set "DRAFTBOT_WAIT_TIMEOUT=300"
if not defined DRAFTBOT_TEST_PG_PORT set "DRAFTBOT_TEST_PG_PORT=15433"
set "TIMEOUT=%DRAFTBOT_WAIT_TIMEOUT%"
set "PG_PORT=%DRAFTBOT_TEST_PG_PORT%"
if not defined DRAFTBOT_TEST_PROJECT set "DRAFTBOT_TEST_PROJECT=draftbot-test"
set "PROJECT=%DRAFTBOT_TEST_PROJECT%"
rem --local's Postgres: compose.test.yaml's db in a project of its own, named after this one.
set "LOCAL_PROJECT=%PROJECT%-local"
set "LOCAL_PG=%PROJECT%-local-pg"
set "DC=docker compose -p %PROJECT% -f compose.yaml -f compose.test.yaml"
set "DC_PG=docker compose -p %PROJECT%-local -f compose.yaml -f compose.test.yaml"
set "RUN_BUILD=--build"
set "BUILD_FLAG=--build"
if "%BUILD%"=="0" (set "RUN_BUILD=" & set "BUILD_FLAG=--no-build")

where docker >nul 2>&1 || (call :fail "docker isn't on PATH. Install Docker Desktop or Docker Engine." & exit /b 1)
docker info >nul 2>&1 || (call :fail "Docker isn't running. Start Docker Desktop." & exit /b 1)

set "RC=0"
if "%MODE%"=="unit" call :unit
if "%MODE%"=="unit" set "RC=%ERRORLEVEL%"
if "%MODE%"=="e2e" call :e2e
if "%MODE%"=="e2e" set "RC=%ERRORLEVEL%"
if "%MODE%"=="all" call :all
if "%MODE%"=="all" set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (echo Tests passed.) else (1>&2 echo Tests failed ^(exit %RC%^).)
exit /b %RC%

:unit
if "%LOCAL%"=="1" (call :run_local) else (call :run_unit)
exit /b

:all
call :unit
set "UNIT_RC=%ERRORLEVEL%"
rem The pytest arguments name unit tests; the e2e suite runs whole.
set "PYARGS="
call :e2e
set "E2E_RC=%ERRORLEVEL%"
set "UNIT_RESULT=passed"
if not "%UNIT_RC%"=="0" set "UNIT_RESULT=failed (%UNIT_RC%)"
set "E2E_RESULT=passed"
if not "%E2E_RC%"=="0" set "E2E_RESULT=failed (%E2E_RC%)"
echo.
echo unit: %UNIT_RESULT%   e2e: %E2E_RESULT%
if not "%UNIT_RC%"=="0" exit /b %UNIT_RC%
exit /b %E2E_RC%

rem The unit suite in the tests container.
:run_unit
call :step Unit suite in a clean %PROJECT% stack
call :teardown
%DC% --profile unit run --rm %RUN_BUILD% tests pytest -n auto -p no:cacheprovider %PYARGS%
set "STEP_RC=%ERRORLEVEL%"
call :teardown
exit /b %STEP_RC%

rem The unit suite on the host, against a Postgres container on tmpfs.
:run_local
call :step Unit suite on this machine (uv), Postgres on 127.0.0.1:%PG_PORT%
where uv >nul 2>&1 || (call :fail "uv isn't on PATH. Install it from https://docs.astral.sh/uv/." & exit /b 1)
set "PG_RUNNING="
for /f %%i in ('docker ps -q --filter "name=^%LOCAL_PG%$"') do set "PG_RUNNING=1"
if defined PG_RUNNING (call :fail "%LOCAL_PG% is running: another --local run of %PROJECT%, or one that was killed. Set DRAFTBOT_TEST_PROJECT to run beside it, or remove it: scripts\clean_containers.bat --project %LOCAL_PROJECT%" & exit /b 1)
call :local_pg_down
%DC_PG% run -d --rm --name %LOCAL_PG% -p 127.0.0.1:%PG_PORT%:5432 db >nul
if errorlevel 1 (call :local_pg_down & call :fail "Couldn't start Postgres. Is port %PG_PORT% free? Set DRAFTBOT_TEST_PG_PORT." & exit /b 1)
rem Over TCP: the image's first-boot server only listens on its socket.
set /a WAITED=0
:pg_wait
docker exec %LOCAL_PG% pg_isready -q -h 127.0.0.1 -U draftbot -d draftbot >nul 2>&1
if not errorlevel 1 goto pg_ready
set /a WAITED+=1
if %WAITED% geq %TIMEOUT% (
    call :local_pg_down
    call :fail "Postgres wasn't ready after %TIMEOUT%s."
    exit /b 1
)
rem One second: ping waits a second between its two pings. timeout.exe refuses redirected input.
ping -n 2 127.0.0.1 >nul
goto pg_wait
:pg_ready
set "DATABASE_URL=postgres://draftbot:test@127.0.0.1:%PG_PORT%/draftbot"
set "DJANGO_SECRET_KEY=test-only-not-secret"
set "DEBUG=false"
set "DEV_CONTROL=false"
uv run --frozen pytest -n auto %PYARGS%
set "STEP_RC=%ERRORLEVEL%"
call :local_pg_down
exit /b %STEP_RC%

rem The browser suite: the whole app against the simulator, then tests\e2e in its container.
:e2e
call :step End-to-end suite in a clean %PROJECT% stack
call :teardown
if not exist test-results\e2e mkdir test-results\e2e
%DC% --profile e2e up -d %BUILD_FLAG% --wait --wait-timeout %TIMEOUT% chrome control-panel bot scheduler
if errorlevel 1 goto e2e_unhealthy
rem tests\e2e\pytest.ini has the options (no cache, artefacts to test-results\).
%DC% --profile e2e run --rm --no-deps %RUN_BUILD% e2e pytest %PYARGS%
set "STEP_RC=%ERRORLEVEL%"
if "%STEP_RC%"=="0" goto e2e_done
1>&2 echo.
1>&2 echo --- last log lines: web bot scheduler discord-sim ---
%DC% --profile e2e logs --no-color --tail 40 web bot scheduler discord-sim 1>&2
1>&2 echo Traces and screenshots: test-results\e2e\
:e2e_done
call :teardown
exit /b %STEP_RC%
:e2e_unhealthy
1>&2 echo.
1>&2 echo --- docker compose ps ---
%DC% --profile e2e ps -a 1>&2
1>&2 echo.
1>&2 echo --- last log lines ---
%DC% --profile e2e logs --no-color --tail 40 1>&2
call :teardown
1>&2 echo ERROR: the e2e stack didn't become healthy.
exit /b 1

:teardown
%DC% --profile "*" down -v --remove-orphans >nul 2>&1
exit /b 0

:local_pg_down
%DC_PG% down -v --remove-orphans >nul 2>&1
exit /b 0

:step
echo.
echo ==^> %*
exit /b 0

:fail
1>&2 echo.
1>&2 echo ERROR: %~1
exit /b 1

:usage
echo Usage: scripts\test.bat [unit^|e2e^|all] [--local] [--no-build] [-- PYTEST_ARGS...]
echo.
echo   unit        (default) the pytest suite, -n auto, in a clean draftbot-test stack
echo   e2e         the browser tests in tests/e2e against the simulator, web, bot and control panel
echo   all         unit, then e2e; fails if either fails
echo   --local     run the unit suite on this machine with uv, against a tmpfs Postgres container
echo               (the fastest loop; needs `uv sync` once)
echo   --no-build  use the images already built
echo   -h, --help  show this help
echo.
echo Arguments after -- go to pytest, e.g. scripts\test.bat -- tests/test_flow.py -k ready. With `all`
echo they go to the unit suite only.
echo Every stack is torn down afterwards (down -v), pass or fail.
echo.
echo Env: DRAFTBOT_WAIT_TIMEOUT   seconds to wait for health checks (default 300)
echo      DRAFTBOT_TEST_PG_PORT   host port of the --local Postgres (default 15433)
echo      DRAFTBOT_TEST_PROJECT   compose project name (default draftbot-test), to run beside
echo                              another test stack; give that one its own TEST_EDGE_SUBNET,
echo                              TEST_EDGE_IP and TEST_EDGE_IP_RANGE too. --local's Postgres is
echo                              the project's db service, in project ^<name^>-local
exit /b 0
