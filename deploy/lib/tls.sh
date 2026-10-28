#!/usr/bin/env bash
set -euo pipefail

SUSPECT_TLS_DIR="${SUSPECT_TLS_DIR:-${SUSPECT_ETC_DIR:-/etc/suspect-interrogation}/tls}"
SUSPECT_TLS_LAN_IP="${SUSPECT_TLS_LAN_IP:-192.168.2.109}"
# 额外要写进证书 SAN 的地址，逗号分隔，每项形如 "IP:1.2.3.4" 或 "DNS:host.name"。
# 用途：同一张证书要同时服务多个入口（例如局域网直连 + frp 公网映射）时，
# 把浏览器地址栏里实际使用的主机逐个列进来 —— WebSocket 不吃"点了继续访问"
# 的证书例外，SAN 不匹配的地址上 WSS 必然失败（2026-10-27 生产故障的根因）。
# 修改此列表会让 _tls_leaf_valid 校验失败，从而在下一次部署时自动重签证书。
SUSPECT_TLS_EXTRA_SAN="${SUSPECT_TLS_EXTRA_SAN:-}"
SUSPECT_TLS_CA_FILE="${SUSPECT_TLS_CA_FILE:-${SUSPECT_TLS_DIR}/ca.crt}"
SUSPECT_TLS_CA_KEY_FILE="${SUSPECT_TLS_CA_KEY_FILE:-${SUSPECT_TLS_DIR}/ca.key}"
SUSPECT_TLS_CERT_FILE="${SUSPECT_TLS_CERT_FILE:-${SUSPECT_TLS_DIR}/server.crt}"
SUSPECT_TLS_KEY_FILE="${SUSPECT_TLS_KEY_FILE:-${SUSPECT_TLS_DIR}/server.key}"
SUSPECT_TLS_CA_DAYS="${SUSPECT_TLS_CA_DAYS:-365}"
SUSPECT_TLS_CERT_DAYS="${SUSPECT_TLS_CERT_DAYS:-90}"
SUSPECT_TLS_RENEW_BEFORE_DAYS="${SUSPECT_TLS_RENEW_BEFORE_DAYS:-30}"

_tls_require_openssl() {
  command -v openssl >/dev/null 2>&1 || {
    printf 'openssl is required for LAN TLS\n' >&2
    return 1
  }
}

_tls_ca_valid() {
  [[ -s "$SUSPECT_TLS_CA_FILE" && -s "$SUSPECT_TLS_CA_KEY_FILE" ]] || return 1
  openssl x509 -in "$SUSPECT_TLS_CA_FILE" -noout >/dev/null 2>&1 || return 1
  openssl pkey -in "$SUSPECT_TLS_CA_KEY_FILE" -noout >/dev/null 2>&1 || return 1
  openssl x509 -checkend 86400 -noout -in "$SUSPECT_TLS_CA_FILE" >/dev/null 2>&1 || return 1
  local cert_pub key_pub
  cert_pub="$(openssl x509 -in "$SUSPECT_TLS_CA_FILE" -pubkey -noout 2>/dev/null | openssl pkey -pubin -outform pem 2>/dev/null)" || return 1
  key_pub="$(openssl pkey -in "$SUSPECT_TLS_CA_KEY_FILE" -pubout -outform pem 2>/dev/null)" || return 1
  [[ "$cert_pub" == "$key_pub" ]]
}

_tls_san_state_file() {
  printf '%s' "${SUSPECT_TLS_CERT_FILE%.crt}.san-list"
}

_tls_expected_san_list() {
  # 归一化后的"当前要求的 SAN 清单"，与证书旁边的 .san-list 状态文件比对。
  # 只比对"要求的都在"是不够的：从列表里删掉一个地址时，老证书仍然满足逐项
  # 检查，却还带着已废弃的 SAN —— 状态文件让任何方向的变更都会触发重签。
  printf '%s|%s' "$SUSPECT_TLS_LAN_IP" "$(printf '%s' "$SUSPECT_TLS_EXTRA_SAN" | tr -d '[:space:]')"
}

_tls_leaf_valid() {
  [[ -s "$SUSPECT_TLS_CERT_FILE" && -s "$SUSPECT_TLS_KEY_FILE" ]] || return 1
  openssl x509 -in "$SUSPECT_TLS_CERT_FILE" -noout >/dev/null 2>&1 || return 1
  openssl pkey -in "$SUSPECT_TLS_KEY_FILE" -noout >/dev/null 2>&1 || return 1
  local renew_seconds=$((SUSPECT_TLS_RENEW_BEFORE_DAYS * 86400))
  openssl x509 -checkend "$renew_seconds" -noout -in "$SUSPECT_TLS_CERT_FILE" >/dev/null 2>&1 || return 1
  openssl verify -CAfile "$SUSPECT_TLS_CA_FILE" "$SUSPECT_TLS_CERT_FILE" >/dev/null 2>&1 || return 1
  local sans
  sans="$(openssl x509 -in "$SUSPECT_TLS_CERT_FILE" -noout -ext subjectAltName 2>/dev/null || true)"
  grep -Eq "(^|[ ,])IP Address:${SUSPECT_TLS_LAN_IP}([, ]|$)" <<<"$sans" || return 1
  grep -Eq '(^|[ ,])IP Address:127\.0\.0\.1([, ]|$)' <<<"$sans" || return 1
  grep -Eq '(^|[ ,])DNS:localhost([, ]|$)' <<<"$sans" || return 1
  # SUSPECT_TLS_EXTRA_SAN 里列出的地址也必须逐个在证书上；列表一变就重签，
  # 否则新入口的 WSS 会在浏览器侧静默失败（TLS 层被拦，服务端无日志）。
  if [[ -n "$SUSPECT_TLS_EXTRA_SAN" ]]; then
    local -a entries
    IFS=',' read -ra entries <<<"$SUSPECT_TLS_EXTRA_SAN"
    local entry kind value
    for entry in "${entries[@]}"; do
      entry="$(printf '%s' "$entry" | tr -d '[:space:]')"
      [[ -z "$entry" ]] && continue
      kind="${entry%%:*}"
      value="${entry#*:}"
      case "$kind" in
        IP)
          grep -Eq "(^|[ ,])IP Address:${value}([, ]|$)" <<<"$sans" || return 1
          ;;
        DNS)
          grep -Eq "(^|[ ,])DNS:${value}([, ]|$)" <<<"$sans" || return 1
          ;;
        *)
          printf 'unsupported extra SAN kind: %s (expected IP or DNS)\n' "$entry" >&2
          return 1
          ;;
      esac
    done
  fi
  local state_file
  state_file="$(_tls_san_state_file)"
  if [[ -f "$state_file" ]] && [[ "$(cat "$state_file")" != "$(_tls_expected_san_list)" ]]; then
    return 1
  fi
}

_tls_generate_ca() {
  umask 077
  openssl genrsa -out "$SUSPECT_TLS_CA_KEY_FILE" 4096 >/dev/null 2>&1
  openssl req -x509 -new -sha256 \
    -key "$SUSPECT_TLS_CA_KEY_FILE" \
    -days "$SUSPECT_TLS_CA_DAYS" \
    -subj "/CN=Suspect Interrogation LAN Root CA/O=Suspect Interrogation" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$SUSPECT_TLS_CA_FILE"
}

_tls_alt_names_body() {
  # 固定三个地址与既有部署保持兼容；SUSPECT_TLS_EXTRA_SAN 依次追加。
  printf 'IP.1 = %s\n' "$SUSPECT_TLS_LAN_IP"
  printf 'IP.2 = 127.0.0.1\n'
  printf 'DNS.1 = localhost\n'
  [[ -z "$SUSPECT_TLS_EXTRA_SAN" ]] && return 0
  local index_ip=3 index_dns=2 entry kind value
  local -a entries
  IFS=',' read -ra entries <<<"$SUSPECT_TLS_EXTRA_SAN"
  for entry in "${entries[@]}"; do
    entry="$(printf '%s' "$entry" | tr -d '[:space:]')"
    [[ -z "$entry" ]] && continue
    kind="${entry%%:*}"
    value="${entry#*:}"
    if [[ -z "$value" || "$kind" == "$entry" ]]; then
      printf 'extra SAN entry must look like IP:1.2.3.4 or DNS:host.name, got: %s\n' "$entry" >&2
      return 1
    fi
    case "$kind" in
      IP)
        printf 'IP.%d = %s\n' "$index_ip" "$value"
        index_ip=$((index_ip + 1))
        ;;
      DNS)
        printf 'DNS.%d = %s\n' "$index_dns" "$value"
        index_dns=$((index_dns + 1))
        ;;
      *)
        printf 'unsupported extra SAN kind: %s (expected IP or DNS)\n' "$entry" >&2
        return 1
        ;;
    esac
  done
}

_tls_generate_leaf() {
  local csr config alt_names
  alt_names="$(_tls_alt_names_body)" || return 1
  csr="$(mktemp "${SUSPECT_TLS_DIR}/server.XXXXXX.csr")"
  config="$(mktemp "${SUSPECT_TLS_DIR}/server.XXXXXX.cnf")"
  cat >"$config" <<EOF
[req]
prompt = no
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = ${SUSPECT_TLS_LAN_IP}
O = Suspect Interrogation

[req_ext]
subjectAltName = @alt_names

[v3_server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
$alt_names
EOF
  umask 077
  openssl genrsa -out "$SUSPECT_TLS_KEY_FILE" 3072 >/dev/null 2>&1
  if ! openssl req -new -sha256 \
    -key "$SUSPECT_TLS_KEY_FILE" \
    -config "$config" \
    -out "$csr"; then
    rm -f "$csr" "$config"
    return 1
  fi
  if ! openssl x509 -req -sha256 \
    -in "$csr" \
    -CA "$SUSPECT_TLS_CA_FILE" \
    -CAkey "$SUSPECT_TLS_CA_KEY_FILE" \
    -CAcreateserial \
    -days "$SUSPECT_TLS_CERT_DAYS" \
    -extfile "$config" \
    -extensions v3_server \
    -out "$SUSPECT_TLS_CERT_FILE" >/dev/null 2>&1; then
    rm -f "$csr" "$config" "$SUSPECT_TLS_KEY_FILE"
    return 1
  fi
  rm -f "${SUSPECT_TLS_CA_FILE%.crt}.srl" "$csr" "$config"
}

ensure_tls_material() {
  _tls_require_openssl
  mkdir -p "$SUSPECT_TLS_DIR"
  chmod 0750 "$SUSPECT_TLS_DIR" 2>/dev/null || true
  if [[ "${SUSPECT_DRY_RUN:-0}" != "1" ]]; then
    chown root:"${SUSPECT_SERVICE_GROUP:-suspect-interrogation}" "$SUSPECT_TLS_DIR"
  fi

  local ca_crt_exists=0 ca_key_exists=0
  [[ -e "$SUSPECT_TLS_CA_FILE" ]] && ca_crt_exists=1
  [[ -e "$SUSPECT_TLS_CA_KEY_FILE" ]] && ca_key_exists=1

  if [[ "$ca_crt_exists" -eq 0 && "$ca_key_exists" -eq 0 ]]; then
    _tls_generate_ca
  elif [[ "$ca_crt_exists" -ne "$ca_key_exists" ]] || ! _tls_ca_valid; then
    printf 'existing LAN CA is missing, invalid, mismatched, or expiring; manual CA rotation is required\n' >&2
    return 1
  fi

  if ! _tls_leaf_valid; then
    rm -f "$SUSPECT_TLS_CERT_FILE" "$SUSPECT_TLS_KEY_FILE"
    _tls_generate_leaf
  fi

  # 记录本次签发所要求的 SAN 清单；列表再变时 _tls_leaf_valid 会据此重签。
  printf '%s' "$(_tls_expected_san_list)" > "$(_tls_san_state_file)"

  chmod 0600 "$SUSPECT_TLS_CA_KEY_FILE" 2>/dev/null || true
  chmod 0644 "$SUSPECT_TLS_CA_FILE" "$SUSPECT_TLS_CERT_FILE" 2>/dev/null || true
  chmod 0640 "$SUSPECT_TLS_KEY_FILE" 2>/dev/null || true
  if [[ "${SUSPECT_DRY_RUN:-0}" != "1" ]]; then
    chown root:root "$SUSPECT_TLS_CA_KEY_FILE" "$SUSPECT_TLS_CA_FILE"
    chown root:"${SUSPECT_SERVICE_GROUP:-suspect-interrogation}" "$SUSPECT_TLS_KEY_FILE" "$SUSPECT_TLS_CERT_FILE"
  fi
}

install_tls_trust() {
  [[ "${SUSPECT_DRY_RUN:-0}" == "1" ]] && return 0
  local trust_target="/usr/local/share/ca-certificates/suspect-interrogation-ca.crt"
  local changed=0
  if [[ ! -f "$trust_target" ]] || ! cmp -s "$SUSPECT_TLS_CA_FILE" "$trust_target"; then
    install -o root -g root -m 0644 "$SUSPECT_TLS_CA_FILE" "$trust_target"
    changed=1
  fi
  if [[ "$changed" -eq 1 ]]; then
    command -v update-ca-certificates >/dev/null 2>&1 || {
      printf 'update-ca-certificates is required to trust the LAN CA\n' >&2
      return 1
    }
    update-ca-certificates >/dev/null
  fi
}

curl_tls() {
  curl --fail --silent --show-error --cacert "$SUSPECT_TLS_CA_FILE" "$@"
}
