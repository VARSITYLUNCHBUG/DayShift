#!/bin/sh
# Removes everything the dev and test stacks left behind: their compose projects' containers,
# volumes, networks and the images they built, plus the build/test output in the repo. Finds
# all of it by the compose project label, so it never touches other projects.
# No globbing: resource names are split on whitespace below, never expanded.
set -euf

usage() {
    cat <<'EOF'
Usage: scripts/clean_containers.sh [--project NAME]... [--local-pg] [--outputs]
                                   [--keep-images] [--dry-run]

With no --project: tears down the dev and test compose projects (draftbot-dev, draftbot-test,
and DRAFTBOT_DEV_PROJECT and DRAFTBOT_TEST_PROJECT if set) with their volumes and networks,
removes the images they built, the --local test Postgres (project <name>-local), and the
staticfiles/ and test-results/ folders. Other compose projects and pulled images are left alone.

With --project: only those projects. Their --local Postgres and the output folders go only
when asked for as well.

  --project NAME  clean this project instead of the defaults (repeat for more)
  --local-pg      with --project: also each one's --local test Postgres (NAME-local)
  --outputs       with --project: also remove staticfiles/ and test-results/
  --keep-images   keep the built images (faster next start)
  --dry-run       only print what would be removed
  -h, --help      show this help
EOF
}

PROJECTS=""
LOCAL_PG=0
OUTPUTS=0
KEEP_IMAGES=0
DRY_RUN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --project)
            [ $# -ge 2 ] || { echo "ERROR: --project needs a name." >&2; exit 2; }
            PROJECTS="$PROJECTS $2"
            shift
            ;;
        --local-pg) LOCAL_PG=1 ;;
        --outputs) OUTPUTS=1 ;;
        --keep-images) KEEP_IMAGES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h | --help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
if [ -z "$PROJECTS" ]; then
    # Everything the scripts make, shared pieces included.
    LOCAL_PG=1
    OUTPUTS=1
    PROJECTS="draftbot-dev draftbot-test"
    for extra in "${DRAFTBOT_DEV_PROJECT:-}" "${DRAFTBOT_TEST_PROJECT:-}"; do
        [ -n "$extra" ] || continue
        case " $PROJECTS " in
            *" $extra "*) ;;
            *) PROJECTS="$PROJECTS $extra" ;;
        esac
    done
fi

# scripts/test.sh --local runs its Postgres as project <name>-local.
if [ "$LOCAL_PG" -eq 1 ]; then
    for project in $PROJECTS; do
        case "$project" in *-local) continue ;; esac
        case " $PROJECTS " in
            *" $project-local "*) ;;
            *) PROJECTS="$PROJECTS $project-local" ;;
        esac
    done
fi

cd "$(dirname "$0")/.."

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker isn't on PATH." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker isn't running." >&2; exit 1; }

REMOVED=0
FAILED=0

# remove KIND "NAMES" COMMAND...: prints each name and removes it with COMMAND NAME.
remove() {
    kind=$1
    names=$2
    shift 2
    for name in $names; do
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "  would remove $kind $name"
        elif "$@" "$name" >/dev/null 2>&1; then
            echo "  removed $kind $name"
        else
            echo "  could not remove $kind $name" >&2
            FAILED=1
            continue
        fi
        REMOVED=$((REMOVED + 1))
    done
}

# gone KIND "BEFORE" "AFTER": prints and counts the names compose removed (in BEFORE, not AFTER).
gone() {
    # shellcheck disable=SC2086 # joins the names into one line
    after=" $(printf '%s ' $3)"
    for name in $2; do
        case "$after" in
            *" $name "*) ;;
            *) echo "  removed $1 $name"; REMOVED=$((REMOVED + 1)) ;;
        esac
    done
}

label_containers() { docker ps -a --filter "label=com.docker.compose.project=$1" --format '{{.Names}}'; }
label_volumes() { docker volume ls -q --filter "label=com.docker.compose.project=$1"; }
label_networks() { docker network ls --filter "label=com.docker.compose.project=$1" --format '{{.Name}}'; }
# Images compose built for the project carry its label: tagged ones by name, untagged by id.
label_images() {
    docker image ls --filter "label=com.docker.compose.project=$1" --filter dangling=false \
        --format '{{.Repository}}:{{.Tag}}'
    docker image ls -q --filter "label=com.docker.compose.project=$1" --filter dangling=true
}

# Compose finds a project's resources by its label, so `down` needs no compose file. Run it from
# an empty directory, so it doesn't read this repo's files (and their .env requirement).
EMPTY=$(mktemp -d)
trap 'rmdir "$EMPTY"' EXIT

for project in $PROJECTS; do
    echo "Project $project:"
    before=$REMOVED
    containers=$(label_containers "$project")
    volumes=$(label_volumes "$project")
    networks=$(label_networks "$project")

    # Compose first: it stops the containers in order and drops their volumes and networks.
    if [ "$DRY_RUN" -eq 0 ] && [ -n "$containers$volumes$networks" ]; then
        (cd "$EMPTY" && docker compose -p "$project" down -v --remove-orphans >/dev/null 2>&1) || true
        gone container "$containers" "$(label_containers "$project")"
        gone volume "$volumes" "$(label_volumes "$project")"
        gone network "$networks" "$(label_networks "$project")"
    fi

    # Whatever compose missed: anything still carrying the project label, and its images.
    remove container "$(label_containers "$project")" docker rm -f -v
    remove volume "$(label_volumes "$project")" docker volume rm
    remove network "$(label_networks "$project")" docker network rm
    if [ "$KEEP_IMAGES" -eq 0 ]; then
        remove image "$(label_images "$project")" docker image rm
    fi
    [ "$REMOVED" -ne "$before" ] || echo "  nothing to remove"
done

if [ "$LOCAL_PG" -eq 1 ]; then
    echo "The old fixed-name --local test Postgres:"
    before=$REMOVED
    # What scripts/test.sh --local started before it ran a project of its own.
    remove container "$(docker ps -a --filter name=^draftbot-test-local-pg$ --format '{{.Names}}')" \
        docker rm -f -v
    [ "$REMOVED" -ne "$before" ] || echo "  nothing to remove"
fi

if [ "$OUTPUTS" -eq 1 ]; then
    echo "Output folders in the repo:"
    before=$REMOVED
    for dir in staticfiles test-results; do
        if [ -e "$dir" ]; then remove folder "$dir" rm -rf; fi
    done
    [ "$REMOVED" -ne "$before" ] || echo "  nothing to remove"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run: nothing was removed."
elif [ "$FAILED" -eq 1 ]; then
    echo "Done, but some resources could not be removed (see above)." >&2
    exit 1
else
    echo "Done."
fi
