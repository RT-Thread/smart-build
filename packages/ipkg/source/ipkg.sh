#!/bin/sh

set -eu

ROOT=${IPKG_ROOT:-/}
STATE=${IPKG_STATE_DIR:-$ROOT/var/lib/opkg}
BUSYBOX=${IPKG_BUSYBOX:-/bin/busybox}
INFO_DIR=$STATE/info
STATUS_FILE=$STATE/status
TMP_DIR=

cleanup()
{
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        "$BUSYBOX" rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT INT TERM

die()
{
    echo "ipkg: $*" >&2
    exit 1
}

usage()
{
    cat <<'EOF'
usage: ipkg install PACKAGE.ipk
       ipkg remove PACKAGE
       ipkg list
       ipkg status [PACKAGE]

Environment:
  IPKG_ROOT       target root directory (default /)
  IPKG_STATE_DIR  package database (default $IPKG_ROOT/var/lib/opkg)
EOF
}

safe_package_name()
{
    case "$1" in
        ""|*[!A-Za-z0-9._+-]*) return 1 ;;
        *) return 0 ;;
    esac
}

control_field()
{
    sed -n "s/^$1:[[:space:]]*//p" "$2" | "$BUSYBOX" head -n 1
}

extract_member()
{
    package=$1
    member=$2
    destination=$3
    "$BUSYBOX" ar p "$package" "$member" > "$destination" || die "missing $member in $package"
}

validate_archive()
{
    archive=$1
    members=$2
    verbose=$3
    "$BUSYBOX" tar -tzf "$archive" > "$members" || die "invalid archive: $archive"
    while IFS= read -r member; do
        case "$member" in
            ""|./|/*|../*|*/../*|*/..|..)
                die "unsafe archive member: $member"
                ;;
        esac
    done < "$members"
    "$BUSYBOX" tar -tvzf "$archive" > "$verbose" || die "invalid archive: $archive"
    while IFS= read -r line; do
        case "$line" in
            d*|-*) ;;
            *) die "unsupported archive member in $archive: $line" ;;
        esac
    done < "$verbose"
}

validate_rootfs_path()
{
    path=$1
    current=$ROOT
    old_ifs=$IFS
    set -f
    IFS=/
    set -- $path
    IFS=$old_ifs
    set +f
    for component do
        [ -n "$component" ] || continue
        current=$current/$component
        if [ -L "$current" ]; then
            die "rootfs path traverses symlink: $path"
        fi
    done
}

rebuild_status()
{
    status_new=$STATUS_FILE.new
    : > "$status_new"
    for control in "$INFO_DIR"/*.control; do
        [ -f "$control" ] || continue
        "$BUSYBOX" cat "$control" >> "$status_new"
        printf '\n' >> "$status_new"
    done
    "$BUSYBOX" mv "$status_new" "$STATUS_FILE"
}

install_package()
{
    package=$1
    action=${2:-install}
    [ -f "$package" ] || die "package not found: $package"
    "$BUSYBOX" mkdir -p "$INFO_DIR" "$ROOT"
    TMP_DIR=$($BUSYBOX mktemp -d /tmp/ipkg.XXXXXX) || die "cannot create temporary directory"
    control_archive=$TMP_DIR/control.tar.gz
    control_dir=$TMP_DIR/control
    data_archive=$TMP_DIR/data.tar.gz
    data_dir=$TMP_DIR/data
    members=$TMP_DIR/members
    verbose=$TMP_DIR/verbose
    "$BUSYBOX" mkdir -p "$control_dir" "$data_dir"
    extract_member "$package" control.tar.gz "$control_archive"
    validate_archive "$control_archive" "$TMP_DIR/control.members" "$TMP_DIR/control.verbose"
    "$BUSYBOX" tar -xzf "$control_archive" -C "$control_dir" || die "cannot extract control archive"
    control=$control_dir/control
    [ -f "$control" ] || die "control file missing in $package"
    name=$(control_field Package "$control")
    version=$(control_field Version "$control")
    safe_package_name "$name" || die "unsafe package name: $name"
    [ -n "$version" ] || die "missing package version: $name"
    extract_member "$package" data.tar.gz "$data_archive"
    validate_archive "$data_archive" "$members" "$verbose"
    while IFS= read -r member; do
        member=${member#./}
        [ -n "$member" ] || continue
        validate_rootfs_path "$member"
    done < "$members"
    "$BUSYBOX" tar -xzf "$data_archive" -C "$data_dir" || die "cannot extract data archive"
    if [ -n "$($BUSYBOX find "$data_dir" -type l -print)" ]; then
        die "symbolic links are not supported in IPK data"
    fi

    file_list=$TMP_DIR/files.list
    install_archive=$TMP_DIR/install.tar
    "$BUSYBOX" find "$data_dir" -type f -print | sed "s#^$data_dir/##" > "$file_list"
    old_list=$INFO_DIR/$name.list
    if [ "$action" = upgrade ] && [ -f "$old_list" ]; then
        "$BUSYBOX" cp "$old_list" "$TMP_DIR/old.list"
    fi
    "$BUSYBOX" tar -C "$data_dir" -cf "$install_archive" . || die "cannot prepare package files"
    "$BUSYBOX" tar -C "$ROOT" -xf "$install_archive" || die "cannot install package files"
    if [ "$action" = upgrade ] && [ -f "$TMP_DIR/old.list" ]; then
        while IFS= read -r path; do
            [ -n "$path" ] || continue
            if ! "$BUSYBOX" grep -F -x -q "$path" "$file_list"; then
                validate_rootfs_path "$path"
                "$BUSYBOX" rm -f "$ROOT/$path"
            fi
        done < "$TMP_DIR/old.list"
    fi
    "$BUSYBOX" cp "$file_list" "$INFO_DIR/$name.list.new"
    {
        printf 'Package: %s\n' "$name"
        printf 'Version: %s\n' "$version"
        printf 'Status: install ok installed\n'
        printf 'Architecture: %s\n' "$(control_field Architecture "$control")"
        printf 'Depends: %s\n' "$(control_field Depends "$control")"
        printf 'Provides: %s\n' "$(control_field Provides "$control")"
        printf 'Description: %s\n' "$(control_field Description "$control")"
    } > "$INFO_DIR/$name.control.new"
    "$BUSYBOX" mv "$INFO_DIR/$name.list.new" "$INFO_DIR/$name.list"
    "$BUSYBOX" mv "$INFO_DIR/$name.control.new" "$INFO_DIR/$name.control"
    rebuild_status
    if [ "$action" = upgrade ]; then
        echo "upgraded $name $version"
    else
        echo "installed $name $version"
    fi
}

remove_package()
{
    name=$1
    safe_package_name "$name" || die "unsafe package name: $name"
    list=$INFO_DIR/$name.list
    [ -f "$list" ] || die "package is not installed: $name"
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        validate_rootfs_path "$path"
        "$BUSYBOX" rm -f "$ROOT/$path"
    done < "$list"
    "$BUSYBOX" rm -f "$list" "$INFO_DIR/$name.control"
    [ -f "$STATUS_FILE" ] && rebuild_status
    echo "removed $name"
}

list_packages()
{
    [ -d "$INFO_DIR" ] || exit 0
    for control in "$INFO_DIR"/*.control; do
        [ -f "$control" ] || continue
        printf '%s %s\n' "$(control_field Package "$control")" "$(control_field Version "$control")"
    done
}

status_package()
{
    if [ "$#" -eq 0 ]; then
        list_packages
        return
    fi
    name=$1
    safe_package_name "$name" || die "unsafe package name: $name"
    control=$INFO_DIR/$name.control
    [ -f "$control" ] || die "package is not installed: $name"
    "$BUSYBOX" cat "$control"
}

[ "$#" -gt 0 ] || { usage; exit 1; }
case "$1" in
    --help|-h) usage ;;
    install|upgrade)
        [ "$#" -eq 2 ] || die "$1 requires one package"
        install_package "$2" "$1"
        ;;
    remove|uninstall)
        [ "$#" -eq 2 ] || die "$1 requires one package name"
        remove_package "$2"
        ;;
    list) [ "$#" -eq 1 ] || die "list takes no arguments"; list_packages ;;
    status) shift; status_package "$@" ;;
    *) usage >&2; exit 1 ;;
esac
