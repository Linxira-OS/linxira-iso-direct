#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s --shelly-package PATH --calamares-package PATH --artwork-package PATH --catalog-package PATH --components-package PATH --component-manager-package PATH --completion-agent-package PATH --config-hub-package PATH --package-center-package PATH --gaming-manager-package PATH --chwd-detector-package PATH --hardware-driver-manager-package PATH --recovery-diagnostics-package PATH --update-package PATH --welcome-package PATH --plymouth-theme-directory PATH [--output DIRECTORY]\n' "${0##*/}" >&2
}

profile_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
shelly_package=''
calamares_package=''
artwork_package=''
catalog_package=''
components_package=''
component_manager_package=''
completion_agent_package=''
config_hub_package=''
package_center_package=''
gaming_manager_package=''
chwd_detector_package=''
hardware_driver_manager_package=''
recovery_diagnostics_package=''
update_package=''
welcome_package=''
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
    --catalog-package)
      [[ $# -ge 2 ]] || usage
      catalog_package=$2
      shift 2
      ;;
    --components-package)
      [[ $# -ge 2 ]] || usage
      components_package=$2
      shift 2
      ;;
    --component-manager-package)
      [[ $# -ge 2 ]] || usage
      component_manager_package=$2
      shift 2
      ;;
    --completion-agent-package)
      [[ $# -ge 2 ]] || usage
      completion_agent_package=$2
      shift 2
      ;;
    --config-hub-package)
      [[ $# -ge 2 ]] || usage
      config_hub_package=$2
      shift 2
      ;;
    --package-center-package)
      [[ $# -ge 2 ]] || usage
      package_center_package=$2
      shift 2
      ;;
    --gaming-manager-package)
      [[ $# -ge 2 ]] || usage
      gaming_manager_package=$2
      shift 2
      ;;
    --recovery-diagnostics-package)
      [[ $# -ge 2 ]] || usage
      recovery_diagnostics_package=$2
      shift 2
      ;;
    --chwd-detector-package)
      [[ $# -ge 2 ]] || usage
      chwd_detector_package=$2
      shift 2
      ;;
    --hardware-driver-manager-package)
      [[ $# -ge 2 ]] || usage
      hardware_driver_manager_package=$2
      shift 2
      ;;
    --update-package)
      [[ $# -ge 2 ]] || usage
      update_package=$2
      shift 2
      ;;
    --welcome-package)
      [[ $# -ge 2 ]] || usage
      welcome_package=$2
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

if [[ -z "$shelly_package" || ! -f "$shelly_package" ||
      -z "$calamares_package" || ! -f "$calamares_package" ||
      -z "$artwork_package" || ! -f "$artwork_package" ||
      -z "$catalog_package" || ! -f "$catalog_package" ||
      -z "$components_package" || ! -f "$components_package" ||
      -z "$component_manager_package" || ! -f "$component_manager_package" ||
      -z "$completion_agent_package" || ! -f "$completion_agent_package" ||
      -z "$config_hub_package" || ! -f "$config_hub_package" ||
      -z "$package_center_package" || ! -f "$package_center_package" ||
       -z "$gaming_manager_package" || ! -f "$gaming_manager_package" ||
       -z "$chwd_detector_package" || ! -f "$chwd_detector_package" ||
       -z "$hardware_driver_manager_package" || ! -f "$hardware_driver_manager_package" ||
       -z "$recovery_diagnostics_package" || ! -f "$recovery_diagnostics_package" ||
      -z "$update_package" || ! -f "$update_package" ||
      -z "$welcome_package" || ! -f "$welcome_package" ||
      -z "$plymouth_theme_directory" ||
      ! -f "$plymouth_theme_directory/linxira.plymouth" ||
      ! -f "$plymouth_theme_directory/watermark.png" ||
      ! -f "$plymouth_theme_directory/animation-0001.png" ||
      ! -f "$plymouth_theme_directory/throbber-0001.png" ]]; then
  usage
  exit 2
fi

validate_package_artifact() {
  local artifact=$1
  local expected_name=$2
  shift 2
  local actual_name entry

  read -r actual_name _ < <(pacman -Qp "$artifact")
  if [[ $actual_name != "$expected_name" ]]; then
    printf 'Package artifact contains %s instead of %s: %s\n' \
      "$actual_name" "$expected_name" "$artifact" >&2
    exit 1
  fi
  for entry in "$@"; do
    if ! bsdtar -tf "$artifact" | grep -Fqx "$entry"; then
      printf '%s artifact is missing %s\n' "$expected_name" "$entry" >&2
      exit 1
    fi
  done
}
validate_package_version() {
  local artifact=$1 expected=$2 actual_name actual_version
  read -r actual_name actual_version < <(pacman -Qp "$artifact")
  if [[ $actual_version != "$expected" ]]; then
    printf '%s artifact version is %s instead of %s\n' \
      "$actual_name" "$actual_version" "$expected" >&2
    exit 1
  fi
}
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
catalog_package=$(realpath "$catalog_package")
components_package=$(realpath "$components_package")
component_manager_package=$(realpath "$component_manager_package")
completion_agent_package=$(realpath "$completion_agent_package")
config_hub_package=$(realpath "$config_hub_package")
package_center_package=$(realpath "$package_center_package")
gaming_manager_package=$(realpath "$gaming_manager_package")
chwd_detector_package=$(realpath "$chwd_detector_package")
hardware_driver_manager_package=$(realpath "$hardware_driver_manager_package")
recovery_diagnostics_package=$(realpath "$recovery_diagnostics_package")
update_package=$(realpath "$update_package")
welcome_package=$(realpath "$welcome_package")
plymouth_theme_directory=$(realpath "$plymouth_theme_directory")
validate_package_artifact "$shelly_package" shelly
validate_package_artifact "$calamares_package" calamares \
  usr/lib/calamares/modules/linxirasoftware/libcalamares_viewmodule_linxirasoftware.so \
  usr/lib/calamares/modules/linxirasoftware/module.desc
validate_package_artifact "$artwork_package" linxira-artwork \
  usr/share/doc/linxira-artwork/TRADEMARKS.md
validate_package_artifact "$catalog_package" linxira-catalog \
  usr/share/linxira/catalog/catalog-v2.json \
  usr/share/linxira/catalog/catalog-v2.schema.json \
  usr/share/linxira/catalog/catalog-v3.json \
  usr/share/linxira/catalog/catalog-v3.schema.json \
  usr/share/licenses/linxira-catalog/LICENSE
validate_package_artifact "$components_package" linxira-components \
  usr/bin/linxira-components \
  usr/bin/linxira-components-service \
  usr/bin/linxira-components-worker \
  usr/lib/linxira-components/linxira_components/__main__.py \
  usr/lib/linxira-components/linxira_components/schemas/receipt-v1.schema.json \
  usr/lib/linxira-components/linxira_components/schemas/catalog-v3.schema.json \
  usr/lib/linxira-components/linxira_components/schemas/selection-v1.schema.json \
  usr/lib/linxira-components/linxira_components/schemas/request-plan-v2.schema.json \
  usr/lib/linxira-components/linxira_components/schemas/confirmation-v2.schema.json \
  usr/lib/linxira-components/linxira_components/schemas/receipt-v2.schema.json \
  usr/lib/systemd/system/linxira-components.service \
  usr/lib/systemd/system/linxira-components-worker@.service \
  usr/share/dbus-1/system.d/org.linxira.Components1.conf \
  usr/share/dbus-1/system-services/org.linxira.Components1.service \
  usr/share/polkit-1/actions/org.linxira.components.policy \
  usr/share/licenses/linxira-components/LICENSE
validate_package_version "$components_package" 0.7.0-1
validate_package_artifact "$component_manager_package" linxira-component-manager \
  usr/bin/linxira-component-manager \
  usr/share/applications/org.linxira.ComponentManager.desktop \
  usr/share/licenses/linxira-component-manager/LICENSE
validate_package_artifact "$completion_agent_package" linxira-completion-agent \
  usr/bin/linxira-completion-agent \
  etc/xdg/autostart/org.linxira.Completion.desktop \
  usr/share/licenses/linxira-completion-agent/LICENSE
validate_package_artifact "$config_hub_package" linxira-config-hub \
  usr/bin/linxira-config \
  usr/share/licenses/linxira-config-hub/LICENSE
validate_package_artifact "$package_center_package" linxira-package-center \
  usr/bin/linxira-package-center \
  usr/share/applications/org.linxira.PackageCenter.desktop \
  usr/share/linxira/package-center/VERSION \
  usr/share/licenses/linxira-package-center/LICENSE
validate_package_artifact "$gaming_manager_package" linxira-gaming-manager \
  usr/bin/linxira-gaming-manager \
  usr/share/applications/org.linxira.GamingManager.desktop \
  usr/share/licenses/linxira-gaming-manager/LICENSE
validate_package_artifact "$chwd_detector_package" linxira-chwd-detector \
  usr/bin/linxira-chwd-detector \
  usr/share/doc/linxira-chwd-detector/UPSTREAM.md \
  usr/share/licenses/linxira-chwd-detector/LICENSE
validate_package_version "$chwd_detector_package" 0.1.0-1
validate_package_artifact "$hardware_driver_manager_package" linxira-hardware-driver-manager \
  usr/bin/linxira-hardware-driver-manager \
  usr/share/applications/org.linxira.HardwareDriverManager.desktop \
  usr/share/metainfo/org.linxira.HardwareDriverManager.metainfo.xml \
  usr/share/licenses/linxira-hardware-driver-manager/LICENSE
validate_package_version "$hardware_driver_manager_package" 0.4.0-1
validate_package_artifact "$recovery_diagnostics_package" linxira-recovery-diagnostics \
  usr/bin/linxira-recovery-diagnostics \
  usr/share/applications/org.linxira.RecoveryDiagnostics.desktop \
  usr/share/metainfo/org.linxira.RecoveryDiagnostics.metainfo.xml \
  usr/share/licenses/linxira-recovery-diagnostics/LICENSE
validate_package_artifact "$update_package" linxira-update \
  usr/bin/linxira-update \
  etc/xdg/autostart/linxira-update-tray.desktop \
  usr/lib/systemd/user/linxira-update.timer \
  usr/share/licenses/linxira-update/LICENSE
validate_package_artifact "$welcome_package" linxira-welcome \
  usr/bin/linxira-welcome \
  usr/share/applications/org.linxira.Welcome.desktop \
  etc/xdg/autostart/org.linxira.Welcome.desktop \
  usr/share/linxira/welcome/i18n/zh_CN.json \
  usr/share/licenses/linxira-welcome/LICENSE
if ! bsdtar -tf "$artwork_package" | grep -qx 'usr/share/doc/linxira-artwork/TRADEMARKS.md'; then
  printf 'The artwork artifact does not contain the Linxira brand policy.\n' >&2
  exit 1
fi
if bsdtar -tf "$components_package" | grep -Eq '(__pycache__|\.pyc$)'; then
  printf 'The components artifact contains generated bytecode.\n' >&2
  exit 1
fi
if bsdtar -tf "$component_manager_package" | grep -Eq '(__pycache__|\.pyc$)'; then
  printf 'The component manager artifact contains generated bytecode.\n' >&2
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
package_artifacts=(
  "$shelly_package"
  "$calamares_package"
  "$artwork_package"
  "$catalog_package"
  "$components_package"
  "$component_manager_package"
  "$completion_agent_package"
  "$config_hub_package"
  "$package_center_package"
  "$gaming_manager_package"
  "$chwd_detector_package"
  "$hardware_driver_manager_package"
  "$recovery_diagnostics_package"
  "$update_package"
  "$welcome_package"
)
repo_artifacts=()
for artifact in "${package_artifacts[@]}"; do
  destination="${repo_dir}/$(basename "$artifact")"
  install -Dm644 "$artifact" "$destination"
  repo_artifacts+=("$destination")
done
repo-add "${repo_dir}/linxira-local.db.tar.zst" "${repo_artifacts[@]}"

sed -i "s|@LINXIRA_LOCAL_REPO@|${profile_copy}/linxira-local-repo|g" "${profile_copy}/pacman.conf"
if grep -q '@LINXIRA_LOCAL_REPO@' "${profile_copy}/pacman.conf"; then
  printf 'Could not configure the temporary Linxira build repository.\n' >&2
  exit 1
fi

target_manifest="${profile_copy}/target-packages.x86_64"
candidate_manifest="${profile_copy}/offline-candidate-packages.x86_64"
install -Dm644 "$target_manifest" \
  "${profile_copy}/airootfs/etc/calamares/target-packages.x86_64"
install -Dm644 "$candidate_manifest" \
  "${profile_copy}/airootfs/etc/calamares/offline-candidate-packages.x86_64"
branding_dir="${profile_copy}/airootfs/etc/calamares/branding/linxira"
bsdtar -xOf "$artwork_package" usr/share/linxira/linxira-logo.svg \
  >"${branding_dir}/linxira-logo.svg"

theme_target="${profile_copy}/airootfs/usr/share/plymouth/themes/linxira"
mkdir -p "$theme_target"
cp -a "${plymouth_theme_directory}/." "$theme_target/"
sed -i 's/\r$//' "$theme_target/linxira.plymouth"

mapfile -t target_packages < <(grep -v -E '^[[:space:]]*(#|$)' "$target_manifest")
mapfile -t candidate_packages < <(grep -v -E '^[[:space:]]*(#|$)' "$candidate_manifest")
target_packages+=("${candidate_packages[@]}")
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
