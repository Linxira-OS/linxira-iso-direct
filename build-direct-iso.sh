#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s --shelly-package PATH --calamares-package PATH --artwork-package PATH --plymouth-theme-directory PATH [--output DIRECTORY]\n' "${0##*/}" >&2
}

profile_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config_cli="${profile_dir}/../linxira-config-hub/cli/linxira-config"
welcome_source="${profile_dir}/../linxira-welcome"
catalog_source="${profile_dir}/../linxira-catalog"
shelly_package=''
calamares_package=''
artwork_package=''
plymouth_theme_directory=''
output_dir="${profile_dir}/out"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --shelly-package)
      [[ $# -ge 2 ]] || usage
      shelly_package=$2
      shift 2
      ;;
    --calamares-package)
      [[ $# -ge 2 ]] || usage
      calamares_package=$2
      shift 2
      ;;
    --artwork-package)
      [[ $# -ge 2 ]] || usage
      artwork_package=$2
      shift 2
      ;;
    --plymouth-theme-directory)
      [[ $# -ge 2 ]] || usage
      plymouth_theme_directory=$2
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || usage
      output_dir=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ ! -f "$config_cli" ||
      ! -f "$welcome_source/src/linxira-welcome" ||
      ! -f "$welcome_source/data/org.linxira.Welcome.desktop" ||
      ! -f "$welcome_source/data/autostart/org.linxira.Welcome.desktop" ||
      ! -f "$welcome_source/data/i18n/zh_CN.json" ||
      ! -f "$catalog_source/catalog/catalog-v2.json" ||
      ! -f "$catalog_source/schema/catalog-v2.schema.json" ||
      -z "$shelly_package" || ! -f "$shelly_package" ||
      -z "$calamares_package" || ! -f "$calamares_package" ||
      -z "$artwork_package" || ! -f "$artwork_package" ||
      -z "$plymouth_theme_directory" ||
      ! -f "$plymouth_theme_directory/linxira.plymouth" ||
      ! -f "$plymouth_theme_directory/watermark.png" ||
      ! -f "$plymouth_theme_directory/animation-0001.png" ||
      ! -f "$plymouth_theme_directory/throbber-0001.png" ]]; then
  usage
  exit 2
fi
command -v mkarchiso >/dev/null
command -v pacman >/dev/null
command -v repo-add >/dev/null
command -v unshare >/dev/null
command -v bsdtar >/dev/null
grub_font=/usr/share/grub/unicode.pf2
if [[ ! -f "$grub_font" ]]; then
  printf 'The GRUB Unicode font is required for the graphical boot menu.\n' >&2
  exit 1
fi

shelly_package=$(realpath "$shelly_package")
calamares_package=$(realpath "$calamares_package")
artwork_package=$(realpath "$artwork_package")
plymouth_theme_directory=$(realpath "$plymouth_theme_directory")
read -r shelly_name _ < <(pacman -Qp "$shelly_package")
read -r calamares_name _ < <(pacman -Qp "$calamares_package")
read -r artwork_name _ < <(pacman -Qp "$artwork_package")
if [[ $shelly_name != shelly ]]; then
  printf 'The Shelly artifact does not contain the shelly package.\n' >&2
  exit 1
fi
if [[ $calamares_name != calamares ]]; then
  printf 'The Calamares artifact does not contain the calamares package.\n' >&2
  exit 1
fi
if [[ $artwork_name != linxira-artwork ]]; then
  printf 'The artwork artifact does not contain the linxira-artwork package.\n' >&2
  exit 1
fi
build_parent=$(dirname "$profile_dir")
profile_copy=$(mktemp -d "${build_parent}/.linxira-archiso-profile.XXXXXX")
work_dir=$(mktemp -d "${build_parent}/.linxira-archiso-work.XXXXXX")
pacman_db=''
package_cache=''

cleanup() {
  rm -rf "$profile_copy" "$work_dir" "$pacman_db" "$package_cache" 2>/dev/null || true
}
trap cleanup EXIT

cp -a "${profile_dir}/." "$profile_copy/"
install -Dm644 "$grub_font" "${profile_copy}/grub/fonts/unicode.pf2"
if [[ -e "${profile_copy}/airootfs/etc/systemd/system/multi-user.target.wants/sshd.service" ]] ||
   grep -q 'sshd\.service' "${profile_copy}/profile-symlinks.list"; then
  printf 'The live profile must not enable SSH by default.\n' >&2
  exit 1
fi
install -Dm755 "$config_cli" \
  "${profile_copy}/airootfs/usr/local/bin/linxira-config"
install -Dm755 "$welcome_source/src/linxira-welcome" \
  "${profile_copy}/airootfs/usr/bin/linxira-welcome"
install -Dm644 "$welcome_source/data/org.linxira.Welcome.desktop" \
  "${profile_copy}/airootfs/usr/share/applications/org.linxira.Welcome.desktop"
install -Dm644 "$welcome_source/data/autostart/org.linxira.Welcome.desktop" \
  "${profile_copy}/airootfs/etc/xdg/autostart/org.linxira.Welcome.desktop"
for translation in "$welcome_source"/data/i18n/*.json; do
  install -Dm644 "$translation" \
    "${profile_copy}/airootfs/usr/share/linxira/welcome/i18n/$(basename "$translation")"
done
install -Dm644 "$catalog_source/catalog/catalog-v2.json" \
  "${profile_copy}/airootfs/usr/share/linxira/catalog/catalog-v2.json"
install -Dm644 "$catalog_source/schema/catalog-v2.schema.json" \
  "${profile_copy}/airootfs/usr/share/linxira/catalog/catalog-v2.schema.json"
while IFS='|' read -r link_path link_target; do
  link_target=${link_target%$'\r'}
  [[ -n "$link_path" && -n "$link_target" ]] || continue
  case "$link_path" in
    /*|*../*)
      printf 'Invalid profile symlink path: %s\n' "$link_path" >&2
      exit 1
      ;;
  esac

  mkdir -p "${profile_copy}/$(dirname "$link_path")"
  rm -rf "${profile_copy}/${link_path}"
  ln -s "$link_target" "${profile_copy}/${link_path}"
done <"${profile_copy}/profile-symlinks.list"

repo_dir="${profile_copy}/linxira-local-repo/x86_64"
mkdir -p "$repo_dir" "$output_dir"
install -Dm644 "$shelly_package" "${repo_dir}/$(basename "$shelly_package")"
install -Dm644 "$calamares_package" "${repo_dir}/$(basename "$calamares_package")"
install -Dm644 "$artwork_package" "${repo_dir}/$(basename "$artwork_package")"
repo-add "${repo_dir}/linxira-local.db.tar.zst" \
  "${repo_dir}/$(basename "$shelly_package")" \
  "${repo_dir}/$(basename "$calamares_package")" \
  "${repo_dir}/$(basename "$artwork_package")"

sed -i "s|@LINXIRA_LOCAL_REPO@|${profile_copy}/linxira-local-repo|g" "${profile_copy}/pacman.conf"
if grep -q '@LINXIRA_LOCAL_REPO@' "${profile_copy}/pacman.conf"; then
  printf 'Could not configure the temporary Linxira build repository.\n' >&2
  exit 1
fi

target_manifest="${profile_copy}/target-packages.x86_64"
install -Dm644 "$target_manifest" \
  "${profile_copy}/airootfs/etc/calamares/target-packages.x86_64"
branding_dir="${profile_copy}/airootfs/etc/calamares/branding/linxira"
bsdtar -xOf "$artwork_package" usr/share/linxira/linxira-logo.svg \
  >"${branding_dir}/linxira-logo.svg"

theme_target="${profile_copy}/airootfs/usr/share/plymouth/themes/linxira"
mkdir -p "$theme_target"
cp -a "${plymouth_theme_directory}/." "$theme_target/"
sed -i 's/\r$//' "$theme_target/linxira.plymouth"

mapfile -t target_packages < <(grep -v -E '^[[:space:]]*(#|$)' "$target_manifest")
target_packages+=(amd-ucode intel-ucode)
offline_repo="${profile_copy}/airootfs/opt/linxira/offline-repo/x86_64"
package_cache=$(mktemp -d "${build_parent}/.linxira-target-package-cache.XXXXXX")
pacman_db=$(mktemp -d "${build_parent}/.linxira-pacman-db.XXXXXX")
mkdir -p "$offline_repo" "${pacman_db}/local"
unshare --map-auto --map-root-user pacman --disable-sandbox \
  --config "${profile_copy}/pacman.conf" \
  --dbpath "$pacman_db" \
  --cachedir "$package_cache" \
  --logfile /dev/null \
  --sync --refresh --downloadonly --noconfirm --needed \
  "${target_packages[@]}"

mapfile -t cached_packages < <(find "$package_cache" -maxdepth 1 -type f -name '*.pkg.tar.zst' -print)
for package in "${cached_packages[@]}"; do
  ln "$package" "${offline_repo}/$(basename "$package")"
done
mapfile -t offline_packages < <(find "$offline_repo" -maxdepth 1 -type f -name '*.pkg.tar.zst' -print)
if [[ ${#offline_packages[@]} -eq 0 ]]; then
  printf 'The target offline repository is empty.\n' >&2
  exit 1
fi
repo-add "${offline_repo}/linxira-offline.db.tar.zst" "${offline_packages[@]}"
rm -rf "$pacman_db"
pacman_db=''

sudo -n true

sudo -n env PROFILE_COPY="$profile_copy" WORK_DIR="$work_dir" OUTPUT_DIR="$output_dir" \
  bash -euo pipefail -c '
    cleanup() {
      rm -rf "$PROFILE_COPY" "$WORK_DIR"
    }
    trap cleanup EXIT
    mkarchiso -v -w "$WORK_DIR" -o "$OUTPUT_DIR" "$PROFILE_COPY"
  '
