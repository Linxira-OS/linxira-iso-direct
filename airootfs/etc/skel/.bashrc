[[ $- != *i* ]] && return

if command -v fastfetch >/dev/null 2>&1 && [[ -z ${FASTFETCH_DISABLED:-} ]]; then
    fastfetch --config /etc/fastfetch/config.d/linxira.jsonc
fi
