@echo off
rem Removes everything the dev and test stacks left behind: their compose projects' containers,
rem volumes, networks and the images they built, plus the build/test output in the repo. Finds
rem all of it by the compose project label, so it never touches other projects.
rem The cmd.exe twin of scripts/clean_containers.sh: same flags, same output.
setlocal EnableExtensions DisableDelayedExpansion
rem The repo root, taken before `shift` moves %0.
set "ROOT=%~dp0.."

set "PROJECTS="
set "LOCAL_PG=0"
set "OUTPUTS=0"
set "KEEP_IMAGES=0"
set "DRY_RUN=0"

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--project" goto parse_project
if /i "%~1"=="--local-pg" (set "LOCAL_PG=1" & shift & goto parse)
if /i "%~1"=="--outputs" (set "OUTPUTS=1" & shift & goto parse)
if /i "%~1"=="--keep-images" (set "KEEP_IMAGES=1" & shift & goto parse)
if /i "%~1"=="--dry-run" (set "DRY_RUN=1" & shift & goto parse)
if /i "%~1"=="-h" (call :usage & exit /b 0)
if /i "%~1"=="--help" (call :usage & exit /b 0)
1>&2 echo Unknown option: %~1
1>&2 echo.
call :usage 1>&2
exit /b 2
:parse_project
if "%~2"=="" (1>&2 echo ERROR: --project needs a name.& exit /b 2)
set "PROJECTS=%PROJECTS% %~2"
shift
shift
goto parse
:parsed

if defined PROJECTS goto projects_done
rem Everything the scripts make, shared pieces included.
set "LOCAL_PG=1"
set "OUTPUTS=1"
set "PROJECTS=draftbot-dev draftbot-test"
if defined DRAFTBOT_DEV_PROJECT if /i not "%DRAFTBOT_DEV_PROJECT%"=="draftbot-dev" if /i not "%DRAFTBOT_DEV_PROJECT%"=="draftbot-test" set "PROJECTS=%PROJECTS% %DRAFTBOT_DEV_PROJECT%"
if defined DRAFTBOT_TEST_PROJECT if /i not "%DRAFTBOT_TEST_PROJECT%"=="draftbot-dev" if /i not "%DRAFTBOT_TEST_PROJECT%"=="draftbot-test" if /i not "%DRAFTBOT_TEST_PROJECT%"=="%DRAFTBOT_DEV_PROJECT%" set "PROJECTS=%PROJECTS% %DRAFTBOT_TEST_PROJECT%"
:projects_done
rem scripts\test.bat --local runs its Postgres as project <name>-local.
if not "%LOCAL_PG%"=="1" goto local_projects_done
set "BASE_PROJECTS=%PROJECTS%"
for %%P in (%BASE_PROJECTS%) do call :add_local %%P
:local_projects_done

cd /d "%ROOT%"
where docker >nul 2>&1 || (1>&2 echo ERROR: docker isn't on PATH.& exit /b 1)
docker info >nul 2>&1 || (1>&2 echo ERROR: Docker isn't running.& exit /b 1)

set "REMOVED=0"
set "FAILED=0"
set "LIST=%TEMP%\draftbot-clean-%RANDOM%.txt"
rem Compose finds a project's resources by its label, so `down` needs no compose file. It runs
rem from an empty directory, so it doesn't read this repo's files (and their .env requirement).
set "EMPTY=%TEMP%\draftbot-clean-%RANDOM%"
mkdir "%EMPTY%"

for %%P in (%PROJECTS%) do call :project %%P
if "%LOCAL_PG%"=="1" call :local_pg
if "%OUTPUTS%"=="1" call :folders
if exist "%LIST%" del "%LIST%"
rmdir "%EMPTY%"

if "%DRY_RUN%"=="1" (
    echo Dry run: nothing was removed.
    exit /b 0
)
if "%FAILED%"=="1" (
    1>&2 echo Done, but some resources could not be removed, see above.
    exit /b 1
)
echo Done.
exit /b 0

:project
set "PROJECT=%~1"
set "FILTER=label=com.docker.compose.project=%PROJECT%"
echo Project %PROJECT%:
set "BEFORE=%REMOVED%"
docker ps -a --filter "%FILTER%" --format "container {{.Names}}" > "%LIST%"
docker volume ls --filter "%FILTER%" --format "volume {{.Name}}" >> "%LIST%"
docker network ls --filter "%FILTER%" --format "network {{.Name}}" >> "%LIST%"
rem Compose first: it stops the containers in order and drops their volumes and networks.
if "%DRY_RUN%"=="0" for %%F in ("%LIST%") do if %%~zF gtr 0 call :compose_down
rem Whatever compose missed: anything still carrying the project label, and its images.
for /f "delims=" %%N in ('docker ps -a --filter "%FILTER%" --format "{{.Names}}"') do call :remove container %%N
for /f "delims=" %%N in ('docker volume ls -q --filter "%FILTER%"') do call :remove volume %%N
for /f "delims=" %%N in ('docker network ls --filter "%FILTER%" --format "{{.Name}}"') do call :remove network %%N
if "%KEEP_IMAGES%"=="1" goto project_images_done
for /f "delims=" %%N in ('docker image ls --filter "%FILTER%" --filter "dangling=false" --format "{{.Repository}}:{{.Tag}}"') do call :remove image %%N
for /f "delims=" %%N in ('docker image ls -q --filter "%FILTER%" --filter "dangling=true"') do call :remove image %%N
:project_images_done
if "%REMOVED%"=="%BEFORE%" echo   nothing to remove
exit /b 0

:compose_down
pushd "%EMPTY%"
docker compose -p %PROJECT% down -v --remove-orphans >nul 2>&1
popd
for /f "usebackq tokens=1,2" %%A in ("%LIST%") do call :gone %%A %%B
exit /b 0

:add_local
set "NAME=%~1"
if /i "%NAME:~-6%"=="-local" exit /b 0
echo " %PROJECTS% " | findstr /i /c:" %NAME%-local " >nul && exit /b 0
set "PROJECTS=%PROJECTS% %NAME%-local"
exit /b 0

rem What scripts\test.bat --local started before it ran a project of its own.
:local_pg
echo The old fixed-name --local test Postgres:
set "BEFORE=%REMOVED%"
for /f "delims=" %%N in ('docker ps -a --filter "name=^draftbot-test-local-pg$" --format "{{.Names}}"') do call :remove container %%N
if "%REMOVED%"=="%BEFORE%" echo   nothing to remove
exit /b 0

:folders
echo Output folders in the repo:
set "BEFORE=%REMOVED%"
for %%D in (staticfiles test-results) do if exist "%%D\" call :remove folder %%D
if "%REMOVED%"=="%BEFORE%" echo   nothing to remove
exit /b 0

rem :remove KIND NAME prints NAME and removes it (or only prints it with --dry-run).
:remove
if "%DRY_RUN%"=="1" (
    echo   would remove %~1 %~2
    set /a REMOVED+=1
    exit /b 0
)
call :rm_%~1 "%~2"
if errorlevel 1 (
    1>&2 echo   could not remove %~1 %~2
    set "FAILED=1"
    exit /b 0
)
echo   removed %~1 %~2
set /a REMOVED+=1
exit /b 0

rem :gone KIND NAME prints and counts NAME if compose removed it (it no longer exists).
:gone
docker %~1 inspect "%~2" >nul 2>&1
if not errorlevel 1 exit /b 0
echo   removed %~1 %~2
set /a REMOVED+=1
exit /b 0

:rm_container
docker rm -f -v "%~1" >nul 2>&1
exit /b

:rm_volume
docker volume rm "%~1" >nul 2>&1
exit /b

:rm_network
docker network rm "%~1" >nul 2>&1
exit /b

:rm_image
docker image rm "%~1" >nul 2>&1
exit /b

:rm_folder
rmdir /s /q "%~1" >nul 2>&1
if exist "%~1\" exit /b 1
exit /b 0

:usage
echo Usage: scripts\clean_containers.bat [--project NAME]... [--local-pg] [--outputs]
echo                                     [--keep-images] [--dry-run]
echo.
echo With no --project: tears down the dev and test compose projects (draftbot-dev, draftbot-test,
echo and DRAFTBOT_DEV_PROJECT and DRAFTBOT_TEST_PROJECT if set) with their volumes and networks,
echo removes the images they built, the --local test Postgres (project ^<name^>-local), and the
echo staticfiles/ and test-results/ folders. Other compose projects and pulled images are left alone.
echo.
echo With --project: only those projects. Their --local Postgres and the output folders go only
echo when asked for as well.
echo.
echo   --project NAME  clean this project instead of the defaults (repeat for more)
echo   --local-pg      with --project: also each one's --local test Postgres (NAME-local)
echo   --outputs       with --project: also remove staticfiles/ and test-results/
echo   --keep-images   keep the built images (faster next start)
echo   --dry-run       only print what would be removed
echo   -h, --help      show this help
exit /b 0
